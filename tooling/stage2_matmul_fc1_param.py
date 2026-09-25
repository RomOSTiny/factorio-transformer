"""fc1 matmul instance (N_IN=4, N_OUT=8, +relu) for the Sequencer DAG."""
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

Wfc1 = W_["Wfc1"]
bfc1 = W_["bfc1"]
H2_FP = SEQ["h2_fp"]
T = len(H2_FP)
N_IN = W_["dim"]
N_OUT = W_["ffn"]
EXPECTED_REF = SEQ["fc1_fp"]

bp_string, idmap, expected, meta = build_matmul(
    "Matmul-fc1 parametrized (spatial dot-product+bias+relu, live input buffer)",
    N_IN, N_OUT, Wfc1, bfc1, H2_FP, T, relu=True,
)

assert expected == EXPECTED_REF, (expected, EXPECTED_REF)

with open("stage2_matmul_fc1_param_blueprint.txt", "w") as f:
    f.write(bp_string)
with open("stage2_matmul_fc1_param_ids.json", "w") as f:
    json.dump(idmap, f)

print(f"meta: {meta}")
print(f"draftsman warnings: {len(_caught_warnings)}")
for w in _caught_warnings[:30]:
    print("   ", w)
print(f"EXPECT: {expected}")
print("Saved stage2_matmul_fc1_param_blueprint.txt")
