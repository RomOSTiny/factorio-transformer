"""fc2 matmul instance (N_IN=8, N_OUT=4) for the Sequencer DAG."""
import json
import warnings

_caught_warnings = []
def _showwarning(message, *args, **kwargs):
    _caught_warnings.append(str(message))
warnings.showwarning = _showwarning

from matmul_gen_lib import build_matmul

with open("stage2_smoke_weights.json") as f:
    W_ = json.load(f)
with open("stage2_sequencer_ref.json") as f:
    SEQ = json.load(f)

Wfc2 = W_["Wfc2"]
bfc2 = W_["bfc2"]
FC1_FP = SEQ["fc1_fp"]
T = len(FC1_FP)
N_IN = W_["ffn"]
N_OUT = W_["dim"]
EXPECTED_REF = SEQ["fc2_fp"]

bp_string, idmap, expected, meta = build_matmul(
    "Matmul-fc2 parametrized (spatial dot-product+bias, live input buffer)",
    N_IN, N_OUT, Wfc2, bfc2, FC1_FP, T,
)

assert expected == EXPECTED_REF, (expected, EXPECTED_REF)

with open("stage2_matmul_fc2_param_blueprint.txt", "w") as f:
    f.write(bp_string)
with open("stage2_matmul_fc2_param_ids.json", "w") as f:
    json.dump(idmap, f)

print(f"meta: {meta}")
print(f"draftsman warnings: {len(_caught_warnings)}")
for w in _caught_warnings[:30]:
    print("   ", w)
print(f"EXPECT: {expected}")
print("Saved stage2_matmul_fc2_param_blueprint.txt")
