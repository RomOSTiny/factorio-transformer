"""logits matmul instance (N_IN=DIM=4, N_OUT=VOCAB=4) for the Sequencer DAG -
weight-tied to tok_emb (transposed), no bias, LAST POSITION ONLY (next-token
prediction only ever needs the last position's logits)."""
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

DIM = W_["dim"]
VOCAB = W_["vocab_size"]
TOK_EMB = W_["tok_emb"]     # [VOCAB][DIM]
XF_FP = SEQ["xf_fp"]
LAST = len(XF_FP) - 1
X_LAST = [XF_FP[LAST]]     # T=1: only the last position matters for next-token
W_LOGITS = [[TOK_EMB[vi][i] for vi in range(VOCAB)] for i in range(DIM)]   # transpose: W[i][vi]
B_ZERO = [0.0] * VOCAB
EXPECTED_REF = [SEQ["logits_fp"]]

bp_string, idmap, expected, meta = build_matmul(
    "Matmul-logits parametrized (weight-tied to tok_emb, last position only)",
    DIM, VOCAB, W_LOGITS, B_ZERO, X_LAST, 1,
)

assert expected == EXPECTED_REF, (expected, EXPECTED_REF)

with open("stage2_matmul_logits_param_blueprint.txt", "w") as f:
    f.write(bp_string)
with open("stage2_matmul_logits_param_ids.json", "w") as f:
    json.dump(idmap, f)

print(f"meta: {meta}")
print(f"draftsman warnings: {len(_caught_warnings)}")
for w in _caught_warnings[:30]:
    print("   ", w)
print(f"EXPECT: {expected}  (next_token = argmax = {SEQ['next_token']})")
print("Saved stage2_matmul_logits_param_blueprint.txt")
