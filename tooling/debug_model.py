"""Stage-by-stage comparison of the whole-model blueprint (circuit_sim) with the reference, first positions.

Usage: python debug_model.py [n_positions] [start]
"""
import json
import sys

import numpy as np

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
START = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
sys.argv = sys.argv[:1]
import stage2_real_ref as R
from circuit_sim import GREEN_OUT, RED_IN, RED_OUT, Sim
from model_gen import POS_SIG, TOK_SIG

info = json.load(open("model_info.json"))
ids = json.load(open("model_ids.json"))
dims, ffs, vocab = info["dims"], info["ffs"], info["vocab"]
toks = np.load("stage2_data.npy")[START:START + N].astype(np.int64)
P = R.P
D = R.DIM


def ref_stages(tokens):
    tok, pos = R.q(P["tok_emb.weight"]), R.q(P["pos_emb.weight"])
    x = np.stack([tok[t] + pos[i] for i, t in enumerate(tokens)])
    st = {"emb": x}
    for L in range(R.LAYERS):
        pre = f"blocks.{L}."
        h = R.layernorm(x, P[pre + "ln1.weight"], P[pre + "ln1.bias"])
        qkv = R.matmul(h, P[pre + "qkv.weight"], P[pre + "qkv.bias"])
        qq, kk, vv = qkv[:, :D], qkv[:, D:2 * D], qkv[:, 2 * D:]
        att = R.attention_seq(qq, kk, vv, R.HEADS, R.ATT_C)
        x2 = x + R.matmul(att, P[pre + "proj.weight"], P[pre + "proj.bias"])
        h2 = R.layernorm(x2, P[pre + "ln2.weight"], P[pre + "ln2.bias"])
        f1 = np.maximum(0, R.matmul(h2, P[pre + "fc1.weight"], P[pre + "fc1.bias"]))
        x3 = x2 + R.matmul(f1, P[pre + "fc2.weight"], P[pre + "fc2.bias"])
        st.update({f"L{L}_h1": h, f"L{L}_q": qq, f"L{L}_k": kk, f"L{L}_v": vv, f"L{L}_att": att, f"L{L}_x2": x2,
                   f"L{L}_h2": h2, f"L{L}_f1": f1, f"L{L}_x3": x3})
        x = x3
    st["xf"] = R.layernorm(x, P["ln_f.weight"], P["ln_f.bias"])
    return st


def taps():
    t = {"emb": ("emb_e_0", RED_OUT, dims)}
    for L in range(R.LAYERS):
        p = f"L{L}_"
        t.update({p + "h1": (p + "ln1_out", RED_OUT, dims), p + "q": (p + "qkv_resc_0", RED_OUT, dims),
                  p + "k": (p + f"qkv_resc_{D}", GREEN_OUT, dims), p + "v": (p + f"qkv_resc_{2 * D}", GREEN_OUT, dims),
                  p + "att": (p + "att_att_out", RED_OUT, dims), p + "x2": (p + "pass1", RED_OUT, dims),
                  p + "h2": (p + "ln2_out", RED_OUT, dims), p + "f1": (p + "fc1_relu_0", RED_OUT, ffs),
                  p + "x3": (p + "pass2", RED_OUT, dims)})
    t["xf"] = ("lnf_out", RED_OUT, dims)
    return t


ref = ref_stages(list(toks))
sim = Sim(open("model_blueprint.txt").read())
num = {e["id"]: sim.by_pos[(e["x"], e["y"])] for e in ids}
sim.settle(5000)
for i, tk in enumerate(toks):
    sim.set_const(num["ctrl_src"], {TOK_SIG: int(tk), POS_SIG: i, "signal-W": i + 1})
    sim.settle(20000)
    print(f"--- pos {i} tok {int(tk)}")
    for name, (eid, cid, sigs) in taps().items():
        got = sim.net(num[eid], cid)
        got.pop("signal-V", None) if name.endswith(("_q", "_k")) else None     # the V offset rides on Q/K by design
        want = {sigs[d]: int(v) for d, v in enumerate(ref[name][i]) if v}
        ok = got == want
        extra = ""
        if not ok:
            diff = [(k, got.get(k), want.get(k)) for k in sigs if got.get(k) != want.get(k)]
            foreign = [k for k in got if k not in sigs]
            extra = f" ndiff={len(diff)} e.g. {diff[:4]} foreign={foreign[:4]}"
        print(f"  {name:8s} {'OK ' if ok else 'BAD'}{extra}")
    sim.set_const(num["ctrl_src"], {TOK_SIG: int(tk), POS_SIG: i})
    sim.settle(20000)
