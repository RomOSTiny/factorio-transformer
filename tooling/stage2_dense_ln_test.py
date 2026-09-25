"""Live test of the dense LayerNorm on REAL weights: layer-0 ln1 over a real embedding vector."""
import json, warnings, sys
import numpy as np
caught = []
warnings.showwarning = lambda m, *a, **k: caught.append(str(m))
sys.argv = [sys.argv[0]]
import stage2_real_ref as R
from dense_ln_lib import build_dense_ln
from dense_matmul_lib import signal_pool

INTERNAL = {"signal-E", "signal-F", "signal-G", "signal-H", "signal-J", "signal-K", "signal-V", "signal-I", "signal-O",
            "signal-L", "signal-M", "signal-S", "signal-N", "signal-Q", "signal-R", "signal-U", "signal-W"}
pool = [s for s in signal_pool(140) if s not in INTERNAL]
DIM = 32
in_sigs, out_sigs = pool[:DIM], pool[DIM:2 * DIM]
g = np.array(R.P["blocks.0.ln1.weight"]); b = np.array(R.P["blocks.0.ln1.bias"])
data = np.load("stage2_data.npy")
toks = data[100:105].astype(int)
tok, pos = R.q(R.P["tok_emb.weight"]), R.q(R.P["pos_emb.weight"])
X = np.stack([tok[t] + pos[i] for i, t in enumerate(toks)])
x = X[3]
exp = R.layernorm_rom(X, g, b)[3]   # this live test (Reshenie 44) was the ROM LayerNorm
bp_string, idmap, meta = build_dense_ln("dense LN real weights", g.tolist(), b.tolist(), in_sigs, out_sigs, x_values=[int(v) for v in x])
open("dense_ln_test_blueprint.txt", "w").write(bp_string)
json.dump(idmap, open("dense_ln_test_ids.json", "w"))
json.dump(dict(x=[int(v) for v in x], y=[int(v) for v in exp], in_sigs=in_sigs, out_sigs=out_sigs), open("dense_ln_test_expect.json", "w"))
xs = [e["x"] for e in idmap]; ys = [e["y"] for e in idmap]
print(meta)
print("bbox", min(xs), max(xs), min(ys), max(ys), "center", (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, "warnings", len(caught))
for w in caught[:8]: print("  ", w[:220])
print("x", list(x[:8]), "expected out", list(exp[:8]))
