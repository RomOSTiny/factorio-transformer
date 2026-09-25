"""Test of the Newton LayerNorm (P3.5) on REAL vectors: two blocks in one blueprint.

  A: blocks.0.ln1 over the 48 embedding vectors of a real window
  B: ln_f over the 48 final residual-stream vectors of the same window (larger magnitudes)
Writes newton_ln_test_blueprint.txt / _ids.json / _expect.json, then runs circuit_sim over all
48 positions of both blocks (offline gate). Live: block_live.py-based newton_ln_live.py.
"""
import json
import sys
import warnings

import numpy as np

caught = []
warnings.showwarning = lambda m, *a, **k: caught.append(str(m))
sys.argv = [sys.argv[0]]
import stage2_real_ref as R
from circuit_builder import Builder, R as RED
from circuit_sim import RED_OUT, Sim
from dense_attn_lib import SPECIAL
from dense_matmul_lib import signal_pool
from ln_newton_ref import layernorm_row
from newton_ln_lib import place_newton_ln

CTX, START = 48, 1000
dims = [s for s in signal_pool(140) if s not in SPECIAL][:R.DIM]

toks = np.load("stage2_data.npy")[START:START + CTX].astype(np.int64)
tok, pos = R.q(R.P["tok_emb.weight"]), R.q(R.P["pos_emb.weight"])
x0 = np.stack([tok[t] + pos[i] for i, t in enumerate(toks)])
x = x0.copy()
for L in range(R.LAYERS):                      # the forward loop of stage2_real_ref, keeping the residual x
    pre = f"blocks.{L}."
    h = R.layernorm(x, R.P[pre + "ln1.weight"], R.P[pre + "ln1.bias"])
    qkv = R.matmul(h, R.P[pre + "qkv.weight"], R.P[pre + "qkv.bias"])
    att = R.attention_seq(qkv[:, :R.DIM], qkv[:, R.DIM:2 * R.DIM], qkv[:, 2 * R.DIM:], R.HEADS, R.ATT_C)
    x = x + R.matmul(att, R.P[pre + "proj.weight"], R.P[pre + "proj.bias"])
    h = R.layernorm(x, R.P[pre + "ln2.weight"], R.P[pre + "ln2.bias"])
    x = x + R.matmul(np.maximum(0, R.matmul(h, R.P[pre + "fc1.weight"], R.P[pre + "fc1.bias"])), R.P[pre + "fc2.weight"], R.P[pre + "fc2.bias"])
x3 = x
blocks = {
    "A": ("blocks.0.ln1", x0, 2, 0),
    "B": ("ln_f", x3, 2, 12),
}
b = Builder("newton LN test")
exp = {"dims": dims, "blocks": {}}
for name, (wname, X, ox, oy) in blocks.items():
    gq, bq = R.q(R.P[wname + ".weight"]), R.q(R.P[wname + ".bias"])
    place_newton_ln(b, f"{name}_", ox, oy, gq.tolist(), bq.tolist(), dims, dims, R.LN_C)
    b.const(f"{name}_x_src", 0, oy, {})
    b.wire(RED, f"{name}_x_src", f"{name}_xk", s2="input")
    b.const(f"{name}_sink", ox + 8, oy, {})
    b.wire(RED, f"{name}_out", f"{name}_sink", s1="output")
    steps = []
    for i in range(CTX):
        tr = {}
        out = layernorm_row(X[i], gq, bq, R.LN_C, trace=tr)
        assert (out == R.layernorm(X[i:i + 1], R.P[wname + ".weight"], R.P[wname + ".bias"])[0]).all()
        steps.append(dict(x=X[i].tolist(), out=out.tolist(), s=tr["s"], v=tr["v"]))
    exp["blocks"][name] = steps
b.power("A_sub", "B_sub")
b.eei(12, 8)
bp_string, idmap = b.result()
open("newton_ln_test_blueprint.txt", "w").write(bp_string)
json.dump(idmap, open("newton_ln_test_ids.json", "w"))
json.dump(exp, open("newton_ln_test_expect.json", "w"))
print("entities", len(idmap), "per LN block", sum(1 for e in idmap if e["id"].startswith("A_")), "warnings", len(caught))
for w in caught[:5]:
    print("  ", w[:200])
vs = [s["v"] for st in exp["blocks"].values() for s in st]
print("v range", min(vs), max(vs))

# ---- offline gate: circuit_sim over all positions ----
sim = Sim(bp_string)
num = {e["id"]: sim.by_pos[(e["x"], e["y"])] for e in idmap}
vec = lambda v: {dims[d]: int(a) for d, a in enumerate(v) if a}
sim.settle()
bad, max_settle = 0, 0
for i in range(CTX):
    for name in blocks:
        sim.set_const(num[f"{name}_x_src"], vec(exp["blocks"][name][i]["x"]))
    max_settle = max(max_settle, sim.settle())
    for name in blocks:
        got = sim.net(num[f"{name}_out"], RED_OUT)
        want = vec(exp["blocks"][name][i]["out"])
        if got != want:
            bad += 1
            if bad <= 3:
                d = {k: (got.get(k), want.get(k)) for k in set(got) | set(want) if got.get(k) != want.get(k)}
                print(f"SIM MISMATCH block {name} pos {i}: {dict(list(d.items())[:6])}")
print(f"sim: {CTX} positions x {len(blocks)} blocks, mismatches {bad}, max settle {max_settle} ticks")
print("SIM NEWTON LN", "OK" if bad == 0 else "FAILED")
