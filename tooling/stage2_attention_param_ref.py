"""
Numeric reference for the PARAMETRIZED Attention block (Sequencer DAG).

stage2_attention_ref.py only computed position 1 (the interesting softmax
case). The DAG needs BOTH positions, and attention has a GROWING WINDOW:
pos 0 attends to key 0 only; pos 1 attends to keys 0 and 1.

To keep the circuit a FIXED size (no runtime-variable key count), always
compute a 2-key softmax and MASK key 1 out for pos 0: subtract a large
constant BIGMASK from score1 when pos==0, so exp(score1-max) underflows to
0 (its LUT index lands past N_BUCKETS) and weight1 becomes 0. Then
out = w0*V0 + w1*V1 reduces to V0 for pos 0 - exactly what a 1-key softmax
gives.

This file proves that masking reproduces stage2_sequencer_ref.json's
attn_dbg / attn_out_fp for BOTH positions, BEFORE any circuit is built.
"""
import json

with open("stage2_sequencer_ref.json") as f:
    SEQ = json.load(f)
with open("stage2_attention_ref.json") as f:
    ARF = json.load(f)

SCALE = SEQ["SCALE"]
DIM = SEQ["DIM"]
HEAD_DIM = SEQ["HEAD_DIM"]
N_BUCKETS = ARF["N_BUCKETS"]
WIDTH_FP = ARF["WIDTH_FP"]
EXP_TABLE = ARF["exp_table"]
import math
SQRT_HD = math.isqrt(HEAD_DIM)

Q_FP = SEQ["q_fp"]          # [[...],[...]]  per position
K_FP = SEQ["k_fp"]
V_FP = SEQ["v_fp"]
T = len(Q_FP)
EXP_ATTN_OUT = SEQ["attn_out_fp"]
EXP_DBG = SEQ["attn_dbg"]

BIGMASK = 10000            # >> N_BUCKETS*WIDTH_FP (=1600); keeps LUT idx well
# inside int32 and comfortably past the last bucket for any real score.


def trunc_div(a, b):
    aa, bb = abs(a), abs(b)
    r = aa // bb
    return -r if (a < 0) != (b < 0) else r


def dot_scaled(a_fp, b_fp, divisor):
    raw = sum(a_fp[i] * b_fp[i] for i in range(len(a_fp)))
    return trunc_div(trunc_div(raw, SCALE), divisor)


def exp_lut(shifted_fp):
    idx = trunc_div(-shifted_fp, WIDTH_FP)
    if idx >= N_BUCKETS:
        return 0
    return EXP_TABLE[idx]


def attention_masked(pos):
    """Fixed-size 2-key attention with key 1 masked out when pos == 0."""
    q = Q_FP[pos]
    score0 = dot_scaled(q, K_FP[0], SQRT_HD)
    score1 = dot_scaled(q, K_FP[1], SQRT_HD)
    mask = BIGMASK if pos == 0 else 0
    score1_eff = score1 - mask

    max_s = max(score0, score1_eff)
    sh0 = score0 - max_s
    sh1 = score1_eff - max_s
    e0 = exp_lut(sh0)
    e1 = exp_lut(sh1)
    sum_e = e0 + e1
    w0 = trunc_div(e0 * SCALE, sum_e)
    w1 = trunc_div(e1 * SCALE, sum_e)
    out = [trunc_div(w0 * V_FP[0][d] + w1 * V_FP[1][d], SCALE) for d in range(DIM)]
    return dict(score0=score0, score1=score1, score1_eff=score1_eff,
               max_s=max_s, e0=e0, e1=e1, sum_e=sum_e, w0=w0, w1=w1, out=out)


if __name__ == "__main__":
    print(f"SCALE={SCALE} DIM={DIM} HEAD_DIM={HEAD_DIM} SQRT_HD={SQRT_HD} "
          f"N_BUCKETS={N_BUCKETS} WIDTH_FP={WIDTH_FP} BIGMASK={BIGMASK}")
    ok = True
    results = []
    for pos in range(T):
        r = attention_masked(pos)
        results.append(r)
        exp_out = EXP_ATTN_OUT[pos]
        exp_scores = EXP_DBG[pos]["scores_fp"]      # length pos+1
        exp_weights = EXP_DBG[pos]["weights_fp"]
        # our fixed-size scores: [score0, score1] ; ref keeps only the first pos+1
        our_scores = [r["score0"], r["score1"]][:pos + 1]
        our_weights = [r["w0"], r["w1"]][:pos + 1]
        match_out = (r["out"] == exp_out)
        match_sc = (our_scores == exp_scores)
        match_w = (our_weights == exp_weights)
        ok &= match_out and match_sc and match_w
        print(f"\npos {pos}:")
        print(f"  scores  got {our_scores}  ref {exp_scores}   {'OK' if match_sc else 'MISMATCH'}")
        print(f"  weights got {our_weights}  ref {exp_weights}   {'OK' if match_w else 'MISMATCH'}")
        print(f"  out     got {r['out']}  ref {exp_out}   {'OK' if match_out else 'MISMATCH'}")
        print(f"  detail: score1_eff={r['score1_eff']} e0={r['e0']} e1={r['e1']} sum_e={r['sum_e']} w0={r['w0']} w1={r['w1']}")

    print("\nRESULT:", "PASS - masking reproduces both positions" if ok else "FAIL")

    with open("stage2_attention_param_ref.json", "w") as f:
        json.dump({
            "SCALE": SCALE, "DIM": DIM, "HEAD_DIM": HEAD_DIM, "SQRT_HD": SQRT_HD,
            "N_BUCKETS": N_BUCKETS, "WIDTH_FP": WIDTH_FP, "BIGMASK": BIGMASK,
            "exp_table": EXP_TABLE,
            "q_fp": Q_FP, "k_fp": K_FP, "v_fp": V_FP,
            "per_pos": results, "attn_out_fp": EXP_ATTN_OUT,
        }, f, indent=2)
    print("Saved stage2_attention_param_ref.json")
