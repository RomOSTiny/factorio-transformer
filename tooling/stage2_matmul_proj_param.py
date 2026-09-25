"""proj matmul instance (N_IN=4, N_OUT=4) for the Sequencer DAG, generated
via matmul_gen_lib.build_matmul (factored out of the proven QKV instance,
stage2_matmul_param.py, closed live 15.09.2026 exact-first-try)."""
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

Wproj = W_["Wproj"]
bproj = W_["bproj"]
ATTN_OUT = SEQ["attn_out_fp"]
T = len(ATTN_OUT)
N_IN = N_OUT = W_["dim"]
EXPECTED_REF = SEQ["proj_fp"]

bp_string, idmap, expected, meta = build_matmul(
    "Matmul-proj parametrized (spatial dot-product+bias, live input buffer)",
    N_IN, N_OUT, Wproj, bproj, ATTN_OUT, T,
)

assert expected == EXPECTED_REF, (expected, EXPECTED_REF)

with open("stage2_matmul_proj_param_blueprint.txt", "w") as f:
    f.write(bp_string)
with open("stage2_matmul_proj_param_ids.json", "w") as f:
    json.dump(idmap, f)

print(f"meta: {meta}")
print(f"NEAR-OVERLAP pairs: {meta['overlaps']}")
print(f"draftsman warnings: {len(_caught_warnings)}")
for w in _caught_warnings[:30]:
    print("   ", w)
print(f"Blueprint length: {len(bp_string)}")
print(f"EXPECT (matches stage2_sequencer_ref.json proj_fp): {expected}")
print("Saved stage2_matmul_proj_param_blueprint.txt")
