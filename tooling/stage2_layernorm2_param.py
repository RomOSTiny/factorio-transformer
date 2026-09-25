"""LN_ffn instance (x2_fp -> h2_fp) for the Sequencer DAG.

Same combinational LayerNorm core as stage2_layernorm_param.py (now
layernorm_gen_lib.build_layernorm), reused verbatim - only the input
vector differs (gamma=1/beta=0 no-op affine, same as every LN
application in this smoke config).
"""
import json

from layernorm_gen_lib import build_layernorm

with open("stage2_sequencer_ref.json") as f:
    SEQ = json.load(f)

X2_FP = SEQ["x2_fp"]
EXPECTED_REF = SEQ["h2_fp"]
T = len(X2_FP)
N_IN = len(X2_FP[0])
gamma_real = [1.0] * N_IN
beta_real = [0.0] * N_IN

bp_string, idmap, meta = build_layernorm(
    "LN_ffn parametrized (x2 -> h2, live input buffer)",
    X2_FP, gamma_real, beta_real, T,
)

with open("stage2_layernorm2_param_blueprint.txt", "w") as f:
    f.write(bp_string)
with open("stage2_layernorm2_param_ids.json", "w") as f:
    json.dump(idmap, f)

xs = [e["x"] for e in idmap]
ys = [e["y"] for e in idmap]
print(f"bbox local: x[{min(xs):.1f},{max(xs):.1f}] y[{min(ys):.1f},{max(ys):.1f}]")
print(f"meta: {meta}")
print(f"X2_FP={X2_FP}")
print(f"EXPECT h2_fp (signal-X, h1lat_p_i): {EXPECTED_REF}")
print("Saved stage2_layernorm2_param_blueprint.txt")
