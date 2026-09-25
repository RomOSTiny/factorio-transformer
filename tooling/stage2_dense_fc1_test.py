"""Live test of the dense matmul on REAL weights: layer-0 fc1 (32 -> 128, relu), 4096 weights."""
import json, warnings, sys
import numpy as np
caught = []
warnings.showwarning = lambda m, *a, **k: caught.append(str(m))
from dense_matmul_lib import build_dense_matmul, signal_pool, q, SCALE

W = json.load(open("stage2_weights.json"))["weights"]
Wt = np.array(W["blocks.0.fc1.weight"])       # [128][32]
bv = np.array(W["blocks.0.fc1.bias"])
n_out, n_in = Wt.shape
rng = np.random.default_rng(1)
x = rng.integers(-300, 300, n_in)
Wq = np.rint(Wt.T * SCALE).astype(np.int64)
acc = x.astype(np.int64) @ Wq + np.rint(bv * SCALE).astype(np.int64) * SCALE
y = np.where(acc >= 0, acc // SCALE, -((-acc) // SCALE))
y = np.maximum(0, y)
in_sigs, out_sigs = signal_pool(n_in), signal_pool(n_out)
bp_string, idmap, meta = build_dense_matmul("dense fc1 real weights", Wt.T.tolist(), bv.tolist(), in_sigs, out_sigs, relu=True, x_values=[int(v) for v in x])
open("dense_fc1_test_blueprint.txt", "w").write(bp_string)
json.dump(idmap, open("dense_fc1_test_ids.json", "w"))
json.dump(dict(x=[int(v) for v in x], y=[int(v) for v in y], in_sigs=in_sigs, out_sigs=out_sigs), open("dense_fc1_test_expect.json", "w"))
xs = [e["x"] for e in idmap]; ys = [e["y"] for e in idmap]
print(meta)
print("bbox", min(xs), max(xs), min(ys), max(ys), "warnings", len(caught))
for w in caught[:5]: print("  ", w[:200])
print("nonzero outputs", int((y != 0).sum()), "of", n_out)
