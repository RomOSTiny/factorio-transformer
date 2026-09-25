"""
Numeric reference for the Attention block (Этап 2, механика 3 — first
numeric design, "not started even on paper" per PROJECT.md before this).
Same role as stage2_layernorm_ref.py: pure Python, no game, computes the
EXACT fixed-point pipeline a combinator circuit would (Factorio's
truncate-toward-zero integer division, integer-only ROM constants) so the
circuit's expected outputs can be checked bit-exact against this, not just
"close" against the float reference.

Test case: smoke model (stage2_smoke_ref.py, dim=4, 1 head, head_dim=4),
tokens=[0,2], attention at POSITION 1 (attends to itself and position 0 —
the minimal case that actually exercises softmax over >1 element; position
0's attention is trivial, weights=[1.0], not a real test of anything new).

Reuses two already-closed mechanisms verbatim (LayerNorm: Решение 27-34
this project's own history; QKV matmul: Решение 26):
  - LayerNorm fixed-point pipeline (rsqrt table, same shape as
    stage2_layernorm_ref.py) to get h1 at position 0 and 1
  - matmul-with-bias pattern (weight_rom SLOT = N_IN+1, raw_acc then ONE
    trunc_div(., SCALE) rescale) to get Q, K, V at both positions from h1

New part (the actual point of this file): scaled dot-product score,
softmax via a flat (non-logarithmic) exp() lookup table -- validated
numerically in stage2_nonlinearity_check2.py's lut_exp() (linear buckets
over a bounded x<=0 range; the wide-dynamic-range octave/build_addressed_rom
machinery rsqrt needed is NOT needed here, scores don't span orders of
magnitude the way variance does) -- and the weighted sum of V.

Bucket width chosen so SCALE*width is an exact integer (a Factorio
arithmetic-combinator constant must be an int): n_buckets=200, x_min=-16.0
-> width=0.08 -> SCALE*width=8. Still within the previously-validated
range from Решение 16 (128-256 buckets all gave low argmax-flip rates on
the real model; 200 sits inside that range, this file's job is exact
circuit-fidelity, not re-tuning that accuracy study).
"""
import json
import math

with open("stage2_smoke_weights.json") as f:
    ref = json.load(f)

SCALE = 100
DIM = ref["dim"]
HEADS = ref["heads"]
HEAD_DIM = DIM // HEADS
EPS_SCALED = 1
TOKENS = ref["tokens"]

N_BUCKETS = 200
X_MIN = -16.0
WIDTH = -X_MIN / N_BUCKETS
WIDTH_FP = round(SCALE * WIDTH)
assert WIDTH_FP == SCALE * WIDTH, "bucket width must be an exact integer in fixed-point units"

# float reference (stage2_smoke_ref.py), position 1, for bit-exact comparison
EXPECTED_SCORES = [0.0944, 0.0298]
EXPECTED_WEIGHTS = [0.5161, 0.4839]
EXPECTED_OUT = [-0.1396, -0.4392, 0.0742, 0.2152]


def q(x):
    return int(round(x * SCALE))


def trunc_div(a, b):
    """Factorio's arithmetic-combinator division: truncates toward zero."""
    aa, bb = abs(a), abs(b)
    r = aa // bb
    return -r if (a < 0) != (b < 0) else r


# ---- rsqrt table, verbatim from stage2_layernorm_ref.py (already closed
# live 05.09.2026) ----
BUCKETS_PER_OCTAVE = 32
OCTAVE_MIN = 0
OCTAVE_MAX = 30
N_OCTAVES = OCTAVE_MAX - OCTAVE_MIN + 1


def build_rsqrt_table():
    table = {}
    for o in range(OCTAVE_MIN, OCTAVE_MIN + N_OCTAVES):
        for s in range(BUCKETS_PER_OCTAVE):
            rep = round((1 + s / BUCKETS_PER_OCTAVE) * (2 ** o))
            rep = max(rep, 1)
            table[(o, s)] = int(round(SCALE ** 2 / math.sqrt(rep)))
    return table


RSQRT_TABLE = build_rsqrt_table()
RSQRT_FLAT = [RSQRT_TABLE[(OCTAVE_MIN + i // BUCKETS_PER_OCTAVE, i % BUCKETS_PER_OCTAVE)] for i in range(N_OCTAVES * BUCKETS_PER_OCTAVE)]
OCT_LOWER = [2 ** o for o in range(OCTAVE_MIN, OCTAVE_MAX + 1)]


def rsqrt_addr(vpe_fp):
    o = 0
    for k in range(OCTAVE_MIN, OCTAVE_MAX):
        if vpe_fp >= 2 ** (k + 1):
            o += 1
    o = min(o, OCTAVE_MAX)
    oct_lower = OCT_LOWER[o - OCTAVE_MIN]
    diff = vpe_fp - oct_lower
    half_lower = oct_lower // 32
    s = trunc_div(diff, half_lower) if half_lower != 0 else 0
    s = max(0, min(BUCKETS_PER_OCTAVE - 1, s))
    return (o - OCTAVE_MIN) * BUCKETS_PER_OCTAVE + s


def layernorm_fixed(x_real, gamma_real, beta_real):
    x_fp = [q(v) for v in x_real]
    gamma_fp = [q(v) for v in gamma_real]
    beta_fp = [q(v) for v in beta_real]
    n = len(x_fp)
    sum_fp = sum(x_fp)
    mean_fp = trunc_div(sum_fp, n)
    sumsq_fp = sum(v * v for v in x_fp)
    esq_fp = trunc_div(sumsq_fp, n)
    var_fp = esq_fp - mean_fp * mean_fp
    vpe_fp = var_fp + EPS_SCALED
    addr = rsqrt_addr(vpe_fp)
    rsqrt_fp = RSQRT_FLAT[addr]
    out_fp = []
    for i in range(n):
        dx_fp = x_fp[i] - mean_fp
        prod1 = dx_fp * rsqrt_fp
        normed_fp = trunc_div(prod1, SCALE)
        prod2 = normed_fp * gamma_fp[i]
        scaled2 = trunc_div(prod2, SCALE)
        out_fp.append(scaled2 + beta_fp[i])
    return out_fp


# ---- exp table: flat linear buckets, x<=0 only (post max-subtraction) ----
def build_exp_table():
    table = []
    for i in range(N_BUCKETS):
        real_x = -(i + 0.5) * WIDTH
        table.append(int(round(SCALE * math.exp(real_x))))
    return table


EXP_TABLE = build_exp_table()


def exp_lut_fixed(shifted_fp):
    """shifted_fp <= 0 always (post max-subtraction)."""
    idx = trunc_div(-shifted_fp, WIDTH_FP)
    if idx >= N_BUCKETS:
        return 0
    return EXP_TABLE[idx]


# ---- matmul-with-bias, verbatim pattern from stage2_matmul_test_export.py
# (weight_rom SLOT=N_IN+1 per output, one rescale at the end) ----
def matmul_fixed(x_fp, W_real, b_real, n_out):
    n_in = len(x_fp)
    out_fp = []
    for oi in range(n_out):
        raw_acc = sum(q(W_real[ii][oi]) * x_fp[ii] for ii in range(n_in))
        raw_acc += q(b_real[oi]) * SCALE
        out_fp.append(trunc_div(raw_acc, SCALE))
    return out_fp


def dot_scaled_fixed(a_fp, b_fp, divisor):
    """dot(a,b) rescaled by SCALE (both operands SCALE-scaled) then by an
    exact-integer divisor (sqrt(HEAD_DIM) here, always an integer for the
    HEAD_DIM values this project's config uses: 4, 8, 16...)."""
    raw = sum(a_fp[i] * b_fp[i] for i in range(len(a_fp)))
    return trunc_div(trunc_div(raw, SCALE), divisor)


def attention_fixed(verbose=True):
    tok_emb, pos_emb = ref["tok_emb"], ref["pos_emb"]
    Wqkv, bqkv = ref["Wqkv"], ref["bqkv"]
    T = len(TOKENS)

    h1_fp = []
    for i, t in enumerate(TOKENS):
        x_real = [tok_emb[t][d] + pos_emb[i][d] for d in range(DIM)]
        h1_fp.append(layernorm_fixed(x_real, [1.0] * DIM, [0.0] * DIM))

    q_fp, k_fp, v_fp = [], [], []
    for i in range(T):
        qkv_fp = matmul_fixed(h1_fp[i], Wqkv, bqkv, 3 * DIM)
        q_fp.append(qkv_fp[:DIM])
        k_fp.append(qkv_fp[DIM:2 * DIM])
        v_fp.append(qkv_fp[2 * DIM:])

    pos = 1  # the interesting case: attends to positions 0 and 1
    assert math.isqrt(HEAD_DIM) ** 2 == HEAD_DIM, "HEAD_DIM must be a perfect square for an exact-integer rescale divisor"
    sqrt_head_dim = math.isqrt(HEAD_DIM)

    scores_fp = [dot_scaled_fixed(q_fp[pos], k_fp[t], sqrt_head_dim) for t in range(pos + 1)]
    max_score_fp = max(scores_fp)
    shifted_fp = [s - max_score_fp for s in scores_fp]
    exp_fp = [exp_lut_fixed(s) for s in shifted_fp]
    sum_exp_fp = sum(exp_fp)
    weights_fp = [trunc_div(e * SCALE, sum_exp_fp) for e in exp_fp]

    out_fp = []
    for d in range(DIM):
        raw = sum(weights_fp[t] * v_fp[t][d] for t in range(pos + 1))
        out_fp.append(trunc_div(raw, SCALE))

    if verbose:
        print(f"h1_fp[0]={h1_fp[0]} h1_fp[1]={h1_fp[1]}")
        print(f"q_fp[1]={q_fp[1]} k_fp[0]={k_fp[0]} k_fp[1]={k_fp[1]}")
        print(f"v_fp[0]={v_fp[0]} v_fp[1]={v_fp[1]}")
        print(f"scores_fp={scores_fp}  (real: {[s / SCALE for s in scores_fp]}, expected {EXPECTED_SCORES})")
        print(f"max_score_fp={max_score_fp} shifted_fp={shifted_fp}")
        print(f"exp_fp={exp_fp} sum_exp_fp={sum_exp_fp}")
        print(f"weights_fp={weights_fp}  (real: {[w / SCALE for w in weights_fp]}, expected {EXPECTED_WEIGHTS})")
        print(f"out_fp={out_fp}  (real: {[o / SCALE for o in out_fp]}, expected {EXPECTED_OUT})")

    return dict(
        h1_fp=h1_fp, q_fp=q_fp, k_fp=k_fp, v_fp=v_fp,
        scores_fp=scores_fp, max_score_fp=max_score_fp, shifted_fp=shifted_fp,
        exp_fp=exp_fp, sum_exp_fp=sum_exp_fp, weights_fp=weights_fp, out_fp=out_fp,
    )


if __name__ == "__main__":
    print(f"SCALE={SCALE} HEAD_DIM={HEAD_DIM} N_BUCKETS={N_BUCKETS} X_MIN={X_MIN} WIDTH_FP={WIDTH_FP}")
    result = attention_fixed()
    out_real = [v / SCALE for v in result["out_fp"]]
    max_err = max(abs(a - b) for a, b in zip(out_real, EXPECTED_OUT))
    print(f"\nmax abs error vs float reference = {max_err:.4f}")

    with open("stage2_attention_ref.json", "w") as f:
        json.dump({
            "SCALE": SCALE, "DIM": DIM, "HEAD_DIM": HEAD_DIM,
            "N_BUCKETS": N_BUCKETS, "X_MIN": X_MIN, "WIDTH_FP": WIDTH_FP,
            "exp_table": EXP_TABLE,
            "rsqrt_table": RSQRT_FLAT,
            "tokens": TOKENS, "position": 1,
            "h1_fp": result["h1_fp"], "q_fp": result["q_fp"], "k_fp": result["k_fp"], "v_fp": result["v_fp"],
            "scores_fp": result["scores_fp"], "max_score_fp": result["max_score_fp"],
            "shifted_fp": result["shifted_fp"], "exp_fp": result["exp_fp"], "sum_exp_fp": result["sum_exp_fp"],
            "weights_fp": result["weights_fp"], "out_fp": result["out_fp"],
            "expected_scores": EXPECTED_SCORES, "expected_weights": EXPECTED_WEIGHTS, "expected_out": EXPECTED_OUT,
        }, f, indent=2)
    print("Saved stage2_attention_ref.json")
