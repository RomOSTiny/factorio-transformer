"""Circuit-exact integer reference for the DELIVERED model (Reshenie 49):
vocab 36, dim 256, 8 layers, 8 heads, ffn 1024, ctx 256 (E:\\dev\\modelgame\\delivery).

Units: activations u = 0.01 (int), weights 0.001 (int), LN gamma/beta 0.01 (int).
Follows the delivery's strict engine emulation (code/engine.py, Quant(strict=True)):
  embeddings   tok = trunc(emb_q / 10), pos likewise               (exact)
  linear       y = trunc((sum x*w_q + b_q*100) / 1000)              (exact)
  attention    score buckets b = round(d / 0.08), d = (top - q.k) / sqrt(hd), cut d <= 16,
               e = exp(-0.08 b) as integer table (EXP_SC), w = trunc(e * 1e4 / sum e),
               att = trunc(sum w*v / 1e4)                           (exact up to the e table)
  logits       trunc(h @ emb_q.T / 1000)                            (exact)
  LayerNorm    integer approximation (the only non-exact stage):
               E = sum x; D = 256 x - E (exact deviation, units u/256)
               dq = 4 x - round(E / 64)  (units u/4); Q = sum dq^2 + EPS_Q
               s = Newton isqrt(Q) = 6400 sigma
               n2 = D * 250 / s (units 0.001); out = trunc((n2 * g_q + b_q * 1000) / 1000)
Every intermediate is tracked against int32.

  python final_ref.py agree [ctx]      per-position argmax: int ref vs their strict emulation vs float
  python final_ref.py gen "<prompt>"   greedy continuation (int ref and their strict)
  python final_ref.py chat             REPORT chat questions, int ref vs their strict
"""
import json
import math
import os
import sys

import numpy as np

DELIVERY = r"E:\dev\modelgame\delivery"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "final_cache")
I32 = 2 ** 31

EXP_SC = 200000             # e table scale: e * 1e4 must stay < 2^31
ATT_OFF = 10 ** 8           # score offset: raw' = q.k + OFF > 0 (|q.k| <= 1000*sqrt(32)*1e4 = 5.7e7)
LN_EPS_Q = 410              # eps 1e-5 in Q units (Q = 4096 * var_u)
LN_NEWTON_ITERS = 4
LN_K_MAX = 15

maxabs = {}


def track(name, a):
    m = int(np.max(np.abs(a))) if np.size(a) else 0
    if m > maxabs.get(name, 0):
        maxabs[name] = m
    return a


def tdiv(a, b):
    """Factorio division: truncation toward zero (b > 0 or array)."""
    a = np.asarray(a, dtype=np.int64)
    q = np.abs(a) // np.abs(b)
    return np.where((a >= 0) == (np.asarray(b) > 0), q, -q)


# ---------------------------------------------------------------- weights

def load_float():
    """Float weights as numpy arrays (json parsed once, cached as npz)."""
    os.makedirs(CACHE, exist_ok=True)
    npz = os.path.join(CACHE, "model_ctx256.npz")
    if not os.path.exists(npz):
        with open(os.path.join(DELIVERY, "model_ctx256.json"), encoding="utf-8") as f:
            obj = json.load(f)
        arrs = {k: np.array(v, dtype=np.float32) for k, v in obj["weights"].items()}
        cfg = {k: obj[k] for k in ("dim", "layers", "heads", "ffn", "context")}
        np.savez(npz, __cfg__=json.dumps(cfg), __vocab__=json.dumps(obj["vocab"]), **arrs)
    z = np.load(npz)
    cfg = json.loads(str(z["__cfg__"]))
    vocab = json.loads(str(z["__vocab__"]))
    return cfg, vocab, {k: z[k] for k in z.files if not k.startswith("__")}


def qw(a):
    """Weight quantization of the engine: round(w * 1000) (float32 like their torch.round)."""
    return np.round(np.asarray(a, dtype=np.float32) * np.float32(1000)).astype(np.int64)


def qln(a):
    return np.round(np.asarray(a, dtype=np.float32) * np.float32(100)).astype(np.int64)


class IntModel:
    def __init__(self):
        self.cfg, self.vocab, P = load_float()
        c = self.cfg
        self.dim, self.layers, self.heads, self.ffn, self.ctx = c["dim"], c["layers"], c["heads"], c["ffn"], c["context"]
        self.hd = self.dim // self.heads
        self.emb_q = qw(P["tok_emb.weight"])                      # (V, D) in 0.001
        self.tok_u = tdiv(self.emb_q, 10)                         # trunc to 0.01
        self.pos_u = tdiv(qw(P["pos_emb.weight"]), 10)
        self.L = []
        for i in range(self.layers):
            p = f"blocks.{i}."
            self.L.append({n: (qw(P[p + n + ".weight"]).T.copy(), qw(P[p + n + ".bias"]))
                           for n in ("qkv", "proj", "fc1", "fc2")})
            for n in ("ln1", "ln2"):
                self.L[i][n] = (qln(P[p + n + ".weight"]), qln(P[p + n + ".bias"]))
        self.lnf = (qln(P["ln_f.weight"]), qln(P["ln_f.bias"]))
        self._att_consts()

    # ------------------------------------------------------------ attention exp table
    def _att_consts(self):
        c = 800.0 * math.sqrt(self.hd)          # one bucket (0.08 of d) in q.k units (1e-4)
        self.att_cut = int(math.floor(16e4 * math.sqrt(self.hd)))          # d <= 16
        nb = int(round(16 / 0.08))                                         # buckets 0..200
        # bucket b = #{thresholds < delta}; threshold b' = floor((b'+0.5) c)
        self.att_thr = np.array([math.floor((b + 0.5) * c) for b in range(nb)], dtype=np.int64)
        self.att_exp = np.array([int(round(EXP_SC * math.exp(-0.08 * b))) for b in range(nb + 1)], dtype=np.int64)

    def exp_of_delta(self, delta):
        b = np.searchsorted(self.att_thr, delta, side="left")
        e = self.att_exp[np.minimum(b, len(self.att_exp) - 1)]
        return np.where(delta <= self.att_cut, e, 0)

    def exp_steps(self):
        """Decider bank form: e(delta) = sum_t [delta <= T_t] * d_t (for the circuit generator)."""
        steps = []
        vals = list(self.att_exp)
        # interval of bucket b: delta in (thr[b-1], thr[b]]; last bucket ends at the cut
        ends = list(self.att_thr) + [self.att_cut]
        for b in range(len(vals)):
            nxt = vals[b + 1] if b + 1 < len(vals) else 0
            if vals[b] != nxt:
                steps.append((int(ends[b]), int(vals[b] - nxt)))
        return steps

    # ------------------------------------------------------------ blocks
    def linear(self, x, name, wb):
        W, b = wb
        acc = track("mm_acc/" + name, x @ W + b * 100)
        return tdiv(acc, 1000)

    def layernorm(self, x, gb):
        g, bta = gb
        x = np.asarray(x, dtype=np.int64)
        E = x.sum(-1, keepdims=True)
        track("ln_E", E)
        D = track("ln_D", self.dim * x - E)
        Er = np.floor_divide(E + 32, 64)                      # round(E/64), half up
        dq = 4 * x - Er
        Q = track("ln_Q", (dq * dq).sum(-1, keepdims=True)) + LN_EPS_Q
        s = np.array([[newton_isqrt(int(v))] for v in Q[:, 0]], dtype=np.int64)
        n2 = tdiv(track("ln_D250", D * 250), s)
        acc = track("ln_acc", n2 * g + bta * 1000)
        return tdiv(acc, 1000)

    def attention(self, q, k, v):
        T = q.shape[0]
        out = np.zeros_like(q)
        causal = np.tril(np.ones((T, T), dtype=bool))
        for h in range(self.heads):
            sl = slice(h * self.hd, (h + 1) * self.hd)
            raw = track("att_raw", q[:, sl] @ k[:, sl].T + ATT_OFF)
            raw_m = np.where(causal, raw, np.int64(-1))
            M = raw_m.max(-1, keepdims=True)
            delta = np.where(causal, M - raw, np.int64(1) << 40)
            e = self.exp_of_delta(delta)
            S = e.sum(-1, keepdims=True)
            w = (e * 10000) // S
            track("att_e1e4", e * 10000)
            acc = track("att_acc", w @ v[:, sl])
            out[:, sl] = tdiv(acc, 10000)
        return out

    def forward(self, tokens, trace=None):
        """trace: dict filled with every intermediate (T x n int arrays), keys like 'L0.h1', 'xf', 'logits'."""
        tokens = np.asarray(tokens, dtype=np.int64)
        T = len(tokens)
        x = self.tok_u[tokens] + self.pos_u[:T]
        D = self.dim
        tr = trace if trace is not None else {}
        tr["x0"] = x
        for i, Lw in enumerate(self.L):
            p = f"L{i}."
            h = tr[p + "h1"] = self.layernorm(x, Lw["ln1"])
            qkv = tr[p + "qkv"] = self.linear(h, "qkv", Lw["qkv"])
            att = tr[p + "att"] = self.attention(qkv[:, :D], qkv[:, D:2 * D], qkv[:, 2 * D:])
            pr = tr[p + "proj"] = self.linear(att, "proj", Lw["proj"])
            x = tr[p + "x2"] = x + pr
            track("x", x)
            h = tr[p + "h2"] = self.layernorm(x, Lw["ln2"])
            f = tr[p + "f1"] = np.maximum(0, self.linear(h, "fc1", Lw["fc1"]))
            f2 = tr[p + "f2"] = self.linear(f, "fc2", Lw["fc2"])
            x = tr[p + "x3"] = x + f2
            track("x", x)
        h = tr["xf"] = self.layernorm(x, self.lnf)
        lg = tr["logits"] = tdiv(track("logit_acc", h @ self.emb_q.T), 1000)
        return lg

    def generate(self, ids, max_new=200, stop_nl=True):
        ids = list(ids)
        new = []
        nl = self.vocab.index("\n")
        while len(ids) < self.ctx and len(new) < max_new:
            nxt = int(np.argmax(self.forward(ids)[-1]))       # np.argmax: first max = smaller index
            ids.append(nxt)
            new.append(nxt)
            if stop_nl and nxt == nl:
                break
        return new


def newton_isqrt(v, iters=LN_NEWTON_ITERS, k_max=LN_K_MAX):
    s = 1 + sum(2 ** (k - 1) for k in range(1, k_max + 1) if v >= 4 ** k)
    for _ in range(iters):
        t = v // s
        s = t // 2 + s // 2
    return s


# ---------------------------------------------------------------- their emulation

def their():
    sys.path.insert(0, os.path.join(DELIVERY, "code"))
    import torch
    import engine
    import model as their_model
    cfg, vocab, P = load_float()
    m = their_model.Model(vocab=len(vocab), **cfg)
    m.load_state_dict({k: torch.tensor(v) for k, v in P.items()}, strict=True)
    m.eval()
    return m, engine, torch


def eval_texts():
    """Dialogues/stories in the model's alphabet (from the delivery REPORT + knowledge)."""
    sys.path.insert(0, os.path.join(DELIVERY, "code"))
    from tokenizer import normalize
    txt = open(os.path.join(DELIVERY, "REPORT.md"), encoding="utf-8").read()
    blocks = [b.strip("\n") for b in txt.split("```")[1::2]]
    out = []
    for b in blocks:
        lines = [normalize(l) for l in b.split("\n")]
        lines = [l.replace("you ", "you: ", 1) if l.startswith("you ") else l for l in lines]
        lines = [l.replace("bot ", "bot: ", 1) if l.startswith("bot ") else l for l in lines]
        s = "\n".join(l for l in lines if l)
        if len(s) > 40:
            out.append(s)
    return out


def cmd_agree(ctx):
    M = IntModel()
    m, engine, torch = their()
    from tokenizer import encode_normalized
    tot = a_int_strict = a_int_float = a_strict_float = 0
    for s in eval_texts():
        ids = encode_normalized(s)[:ctx].astype(np.int64)
        li = M.forward(ids)
        with torch.no_grad():
            x = torch.tensor(ids)[None]
            ls = engine.forward_ext(m, x, engine.Quant(strict=True))[0].numpy()
            lf = m(x)[0].numpy()
        ai, ast, af = li.argmax(-1), ls.argmax(-1), lf.argmax(-1)
        tot += len(ids)
        a_int_strict += int((ai == ast).sum())
        a_int_float += int((ai == af).sum())
        a_strict_float += int((ast == af).sum())
        print(f"len {len(ids):3d}: int=strict {np.mean(ai == ast):.3f} int=float {np.mean(ai == af):.3f} "
              f"strict=float {np.mean(ast == af):.3f}  logit maxdiff int-strict {np.abs(li / 100 - ls).max():.2f}")
    print(f"TOTAL {tot}: int=strict {a_int_strict / tot:.4f}  int=float {a_int_float / tot:.4f}  "
          f"strict=float {a_strict_float / tot:.4f}")
    report_int32()


def report_int32():
    print("max |intermediate|:", {k: f"{v:.2e}" for k, v in sorted(maxabs.items())})
    worst = max(maxabs.items(), key=lambda kv: kv[1])
    print("OVERFLOW! " + worst[0] if worst[1] >= I32 else f"no int32 overflow (worst {worst[0]} {worst[1] / I32:.1%})")


_MODELS = {}


def cmd_gen(prompt, chat=False):
    if not _MODELS:
        _MODELS["int"] = IntModel()
        _MODELS["their"] = their()
    M = _MODELS["int"]
    m, engine, torch = _MODELS["their"]
    from tokenizer import encode_normalized, normalize
    ids = encode_normalized(prompt if chat else normalize(prompt)).tolist()
    a = M.generate(ids, max_new=200, stop_nl=chat)
    b = engine.generate(m, ids, M.ctx, engine.Quant(strict=True), stop_at_newline=chat, max_new=200)
    dec = lambda t: "".join(M.vocab[i] for i in t)
    print("int   :", repr(dec(a)))
    print("strict:", repr(dec(b)))
    return a == b


def cmd_chat():
    qs = ["hi!", "how are you?", "what is your name?", "where do you live?", "tell me a joke.",
          "what are biters?", "what is fulgora?", "thank you!", "bye!"]
    ok = 0
    for q in qs:
        print("you:", q)
        ok += cmd_gen(f"you: {q}\nbot: ", chat=True)
    print(f"identical replies: {ok}/{len(qs)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "agree"
    if cmd == "agree":
        cmd_agree(int(sys.argv[2]) if len(sys.argv) > 2 else 256)
    elif cmd == "gen":
        cmd_gen(sys.argv[2])
    elif cmd == "chat":
        cmd_chat()
