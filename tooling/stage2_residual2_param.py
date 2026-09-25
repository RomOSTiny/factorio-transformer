"""Residual-add #2 (x3 = x2_fp + fc2_fp) for the Sequencer DAG.

Same identity-pair-weight trick as stage2_residual1_param.py, applied to
the second residual connection (post-FFN).
"""
import json
import warnings

_caught_warnings = []
def _showwarning(message, *args, **kwargs):
    _caught_warnings.append(str(message))
warnings.showwarning = _showwarning

from matmul_gen_lib import build_matmul

with open("stage2_sequencer_ref.json") as f:
    SEQ = json.load(f)

X2_FP = SEQ["x2_fp"]
FC2_FP = SEQ["fc2_fp"]
EXPECTED_REF = SEQ["x3_fp"]
T = len(X2_FP)
DIM = len(X2_FP[0])

N_IN = 2 * DIM
N_OUT = DIM
W = [[1.0 if (i == o or i == o + DIM) else 0.0 for o in range(N_OUT)] for i in range(N_IN)]
b = [0.0] * N_OUT
X_ALL = [X2_FP[p] + FC2_FP[p] for p in range(T)]

bp_string, idmap, expected, meta = build_matmul(
    "Residual-add #2 parametrized (x3 = x2 + fc2, live input buffer)",
    N_IN, N_OUT, W, b, X_ALL, T,
)

assert expected == EXPECTED_REF, (expected, EXPECTED_REF)

with open("stage2_residual2_param_blueprint.txt", "w") as f:
    f.write(bp_string)
with open("stage2_residual2_param_ids.json", "w") as f:
    json.dump(idmap, f)

xs = [e["x"] for e in idmap]
ys = [e["y"] for e in idmap]
print(f"bbox local: x[{min(xs):.1f},{max(xs):.1f}] y[{min(ys):.1f},{max(ys):.1f}]")
print(f"meta: {meta}")
print(f"draftsman warnings: {len(_caught_warnings)}")
for w_ in _caught_warnings[:30]:
    print("   ", w_)
print(f"EXPECT: {expected}")
print("Saved stage2_residual2_param_blueprint.txt")
