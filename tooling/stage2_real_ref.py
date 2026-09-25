"""Fixed-point (circuit-exact) reference for the REAL trained model (dim=32, 3 layers,
4 heads, ffn=128, ctx=48, vocab=35) + accuracy study vs the float model.

Circuit semantics reproduced: int arithmetic, truncating division, rsqrt via
octave/sub-bucket ROM, attention exactly as the dense KV-cache circuit computes it
(attn_kv_ref.attn_step: offset scores, max, stepwise exp, softmax), matmul with
bias folded in and ONE rescale, tracked int32 overflow (every intermediate is
checked against 2**31). Usage: python stage2_real_ref.py [SCALE] [N_BUCKETS] [nwin]
"""
import json
import math
import sys

import numpy as np
import torch

from attn_kv_ref import attention_seq, make_consts
from ln_newton_ref import layernorm as ln_newton, make_ln_consts
from stage2_model import TinyGenModel, CONTEXT
from stage2_tokenizer import VOCAB_SIZE

SCALE = int(sys.argv[1]) if len(sys.argv) > 1 else 100
N_BUCKETS = int(sys.argv[2]) if len(sys.argv) > 2 else 200
NWIN = int(sys.argv[3]) if len(sys.argv) > 3 else 20
LN_MODE = sys.argv[4] if len(sys.argv) > 4 else "newton"     # "rom" = Reshenie 44 rsqrt ROM
X_MIN = 16.0
EPS_SCALED = max(1, round(1e-5 * SCALE * SCALE))
OCT_MAX = 30
BPO = 32
I32 = 2 ** 31

W = json.load(open("stage2_weights.json"))
P = {k: np.array(v, dtype=np.float64) for k, v in W["weights"].items()}
DIM, LAYERS, HEADS, FFN = W["dim"], W["layers"], W["heads"], W["ffn"]
HD = DIM // HEADS
maxabs = {}


def track(name, a):
    m = int(np.max(np.abs(a))) if np.size(a) else 0
    if m > maxabs.get(name, 0):
        maxabs[name] = m
    return a


def q(x):
    return np.rint(np.asarray(x) * SCALE).astype(np.int64)


def tdiv(a, b):
    a = np.asarray(a, dtype=np.int64)
    return np.where(a >= 0, a // b, -((-a) // b))


def build_rsqrt():
    t = []
    for o in range(OCT_MAX + 1):
        for s in range(BPO):
            rep = max(round((1 + s / BPO) * (2 ** o)), 1)
            t.append(int(round(SCALE ** 2 / math.sqrt(rep))))
    return t


RSQRT = build_rsqrt()
ATT_C = make_consts(SCALE, N_BUCKETS, HD, X_MIN)
LN_C = make_ln_consts(SCALE, DIM)


def rsqrt_addr(v):
    o = 0
    while o < OCT_MAX and v >= 2 ** (o + 1):
        o += 1
    lo = 2 ** o
    half = lo // 32
    s = int(tdiv(v - lo, half)) if half else 0
    s = max(0, min(BPO - 1, s))
    return o * BPO + s


def layernorm(x, g, b):
    if LN_MODE == "rom":
        return layernorm_rom(x, g, b)
    for r in x:
        track("ln_sumsq", (r * r).sum())
    return ln_newton(x, q(g), q(b), LN_C)


def layernorm_rom(x, g, b):
    """The first (ROM rsqrt) LayerNorm, as built live in Reshenie 44 (dense_ln_lib)."""
    out = np.zeros_like(x)
    gq, bq = q(g), q(b)
    for t in range(x.shape[0]):
        r = x[t]
        mean = int(tdiv(r.sum(), DIM))
        esq = int(tdiv((r * r).sum(), DIM))
        track("ln_sumsq", (r * r).sum())
        var = esq - mean * mean
        rs = RSQRT[rsqrt_addr(var + EPS_SCALED)]
        dx = r - mean
        p1 = track("ln_prod1", dx * rs)
        n = tdiv(p1, SCALE)
        p2 = track("ln_prod2", n * gq)
        out[t] = tdiv(p2, SCALE) + bq
    return out


def matmul(x, Wm, bv):
    Wq = q(Wm.T)
    acc = track("mm_acc", x @ Wq + q(bv) * SCALE)
    return tdiv(acc, SCALE)


def forward(tokens):
    T = len(tokens)
    tok, pos = q(P["tok_emb.weight"]), q(P["pos_emb.weight"])
    x = np.stack([tok[t] + pos[i] for i, t in enumerate(tokens)])
    track("x", x)
    for L in range(LAYERS):
        pre = f"blocks.{L}."
        h = layernorm(x, P[pre + "ln1.weight"], P[pre + "ln1.bias"])
        qkv = matmul(h, P[pre + "qkv.weight"], P[pre + "qkv.bias"])
        qq, kk, vv = qkv[:, :DIM], qkv[:, DIM:2 * DIM], qkv[:, 2 * DIM:]
        for hd in range(HEADS):
            sl = slice(hd * HD, (hd + 1) * HD)
            track("att_dot", qq[:, sl] @ kk[:, sl].T)
        att = attention_seq(qq, kk, vv, HEADS, ATT_C)
        x = x + matmul(att, P[pre + "proj.weight"], P[pre + "proj.bias"])
        h = layernorm(x, P[pre + "ln2.weight"], P[pre + "ln2.bias"])
        f1 = np.maximum(0, matmul(h, P[pre + "fc1.weight"], P[pre + "fc1.bias"]))
        x = x + matmul(f1, P[pre + "fc2.weight"], P[pre + "fc2.bias"])
        track("x", x)
    xf = layernorm(x, P["ln_f.weight"], P["ln_f.bias"])
    logits = tdiv(track("logit_acc", xf @ q(P["tok_emb.weight"]).T), SCALE)
    return logits


def main():
    m = TinyGenModel(VOCAB_SIZE)
    m.load_state_dict({k: torch.tensor(v, dtype=torch.float32) for k, v in W["weights"].items()})
    m.eval()
    data = np.load("stage2_data.npy")
    rng = np.random.default_rng(0)
    starts = rng.integers(0, len(data) - CONTEXT - 1, NWIN)
    agree = fx_ok = fl_ok = n = 0
    margin_bad = []
    for s in starts:
        win = data[s:s + CONTEXT].astype(np.int64)
        tgt = data[s + 1:s + CONTEXT + 1]
        with torch.no_grad():
            fl = m(torch.tensor(win)[None])[0].numpy()
        fx = forward(list(win))
        a_fl, a_fx = fl.argmax(-1), fx.argmax(-1)
        agree += int((a_fl == a_fx).sum())
        fl_ok += int((a_fl == tgt).sum())
        fx_ok += int((a_fx == tgt).sum())
        n += CONTEXT
        for i in np.where(a_fl != a_fx)[0]:
            top2 = np.sort(fl[i])[-2:]
            margin_bad.append(float(top2[1] - top2[0]))
    print(f"SCALE={SCALE} N_BUCKETS={N_BUCKETS} EPS_SCALED={EPS_SCALED} windows={NWIN} predictions={n}")
    print(f"fixed-vs-float argmax agreement: {agree / n:.3f}")
    print(f"float acc vs true next char: {fl_ok / n:.3f}   fixed acc: {fx_ok / n:.3f}")
    if margin_bad:
        print(f"disagreements: {len(margin_bad)}, float top1-top2 margin at them: mean {np.mean(margin_bad):.3f} max {np.max(margin_bad):.3f}")
    worst = max(maxabs.items(), key=lambda kv: kv[1])
    print("max |intermediate| per stage:", {k: f"{v:.2e} ({v / I32:.2%} of int32)" for k, v in sorted(maxabs.items())})
    print("OVERFLOW!" if worst[1] >= I32 else "no int32 overflow")


if __name__ == "__main__":
    main()
