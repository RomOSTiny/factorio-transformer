"""Live test of the dense KV-cache attention (P3) on REAL layer-0 q/k/v of a real text window.

Writes attn_kv_test_blueprint.txt, attn_kv_test_ids.json and attn_kv_test_expect.json
(q/k/v and expected att + per-head intermediates for every position). Driven by attn_kv_live.py.
"""
import json
import sys
import warnings

import numpy as np

caught = []
warnings.showwarning = lambda m, *a, **k: caught.append(str(m))
sys.argv = [sys.argv[0]]
import stage2_real_ref as R
from attn_kv_ref import attn_step, attention_seq
from dense_attn_lib import SPECIAL, build_dense_attn
from dense_matmul_lib import signal_pool

DIM, HEADS, CTX = R.DIM, R.HEADS, 48
START = 1000
pool = [s for s in signal_pool(140) if s not in SPECIAL]
dims, keys = pool[:DIM], pool[DIM:DIM + CTX]

data = np.load("stage2_data.npy")
toks = data[START:START + CTX].astype(np.int64)
tok, pos = R.q(R.P["tok_emb.weight"]), R.q(R.P["pos_emb.weight"])
x = np.stack([tok[t] + pos[i] for i, t in enumerate(toks)])
h = R.layernorm(x, R.P["blocks.0.ln1.weight"], R.P["blocks.0.ln1.bias"])
qkv = R.matmul(h, R.P["blocks.0.qkv.weight"], R.P["blocks.0.qkv.bias"])
Q, K, V = qkv[:, :DIM], qkv[:, DIM:2 * DIM], qkv[:, 2 * DIM:]
C = R.ATT_C
steps = []
for i in range(CTX):
    tr = {}
    att = attn_step(Q[i], K[:i + 1], V[:i + 1], HEADS, C, trace=tr)
    steps.append(dict(q=Q[i].tolist(), k=K[i].tolist(), v=V[i].tolist(), att=att.tolist(),
                      heads={hd: dict(M=t["M"], S=t["S"], e=t["e"], w=t["w"]) for hd, t in tr.items()}))
assert (np.array([s["att"] for s in steps]) == attention_seq(Q, K, V, HEADS, C)).all()

bp_string, idmap, meta = build_dense_attn("dense attention kv test", dims, keys, C, heads=HEADS, n_cells=CTX)
open("attn_kv_test_blueprint.txt", "w").write(bp_string)
json.dump(idmap, open("attn_kv_test_ids.json", "w"))
json.dump(dict(dims=dims, keys=keys, off=C["off"], tokens=toks.tolist(), steps=steps), open("attn_kv_test_expect.json", "w"))
xs = [e["x"] for e in idmap]; ys = [e["y"] for e in idmap]
print(meta)
print("bbox", min(xs), max(xs), min(ys), max(ys), "center", (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, "warnings", len(caught))
for w in caught[:8]:
    print("  ", w[:220])
print("att pos0", steps[0]["att"][:8], "pos47", steps[47]["att"][:8])
