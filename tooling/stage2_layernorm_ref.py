"""
Numeric reference for the LayerNorm block (Reshenie 21 plan, Reshenie 20
rsqrt table params), same role stage2_smoke_ref.py/stage2_matmul_test_export.py's
`expected` played for the matmul block: pure Python, no game, computes the
EXACT fixed-point pipeline (including Factorio's own truncate-toward-zero
integer division - confirmed indirectly from the matmul block's own
verified out_j values, e.g. raw acc_3=-1730 -> out_3=-17, which is trunc(-17.3),
not floor(-18)) so the circuit's expected outputs can be checked bit-exact,
not just "close".

Test input: x[0] = tok_emb[0] + pos_emb[0] from stage2_smoke_weights.json,
i.e. the actual LN1 input at position 0 in the smoke reference model.
Expected output: H1_POS0 (already used and confirmed working as the matmul
block's own x-ROM input) - so a correct LayerNorm block, chained before the
already-closed matmul block, would reproduce a number already proven live
in-game (Reshenie 26).
"""
import json
import math

with open("stage2_smoke_weights.json") as f:
    ref = json.load(f)

SCALE = 100  # same smoke-test scale as stage2_matmul_test_export.py
DIM = ref["dim"]
N_IN = DIM
EPS_SCALED = 1  # same nominal fixed-point eps as stage2_smoke_ref.py's EPS_SCALED

x0_real = [ref["tok_emb"][ref["tokens"][0]][i] + ref["pos_emb"][0][i] for i in range(DIM)]
gamma_real = [1.0] * DIM  # ln1.weight = ones (smoke reference model, stage2_smoke_ref.py)
beta_real = [0.0] * DIM   # ln1.bias = zeros
H1_POS0 = [-1.27, -0.3464, 1.501, 0.1155]  # already used/confirmed in stage2_matmul_test_export.py


def q(x):
    return int(round(x * SCALE))


def trunc_div(a, b):
    """Factorio's arithmetic-combinator division: truncates toward zero,
    NOT floor - confirmed from the matmul block's own verified numbers
    (Reshenie 26 final acc_j/out_j check: acc_3=-1730 -> out_3=-17 means
    -1730/100 resolved to -17, i.e. trunc(-17.3), not floor(-18)=-18)."""
    aa, bb = abs(a), abs(b)
    r = aa // bb
    return -r if (a < 0) != (b < 0) else r


# ---- rsqrt table: same DENSITY validated in Reshenie 20 (32 subbuckets/
# octave, wide octave span) but the addressing math below is written to
# match EXACTLY what the circuit can cheaply compute with combinators - not
# the "-20..20 real-valued octave" framing stage2_export_check.py used for
# its pure-accuracy check. Two corrections found while translating that
# into actual arithmetic-combinator ops (neither is a change to Reshenie
# 20's validated bucket density, both are about which octave LABELS are
# physically reachable once everything is a nonnegative int32 fixed-point
# number):
#
# 1. var_plus_eps_fp is always a NONNEGATIVE integer >=1 (var_fp>=0 for exact
#    real arithmetic, EPS_SCALED>=1 floors it at >=1 even if truncation ever
#    pushes var_fp slightly negative) - so o=floor(log2(vpe_fp)) can never be
#    negative. Reshenie 20's negative octaves existed only in the raw-float
#    check; porting them into fixed point via a log2(SCALE**2) shift (an
#    earlier draft of this file did that) manufactures octaves that no real
#    vpe_fp value could ever land in - dead table space, not wrong, but not
#    what "-20..20" was actually protecting against either.
# 2. The top of the range is bounded by int32, not by the real octave span:
#    vpe_fp itself is an int32 accumulator result, so it can never exceed
#    ~2^31. o=30 (oct_lower=2^30=1073741824) is the highest octave whose
#    lower-bound constant still fits int32 with headroom - o=31 would need
#    2^31, one bit over signed range. Clamping at 30 just stops the table
#    from ever needing a ROM constant draftsman/the game can't hold, it
#    doesn't cost real coverage (nothing legitimately reaches o=31 without
#    vpe_fp itself already having overflowed upstream, a separate concern
#    Reshenie 20 already flagged as "needs rescale, not observed on the
#    real trained model").
#
# Net effect: octave range 0..30 (31 values) instead of a 40-wide span
# starting negative - 992 words instead of 1280, same 32/octave density,
# same validated per-bucket relative precision (a constant offset in where
# the octave axis STARTS doesn't change how finely each octave is divided).
BUCKETS_PER_OCTAVE = 32
OCTAVE_MIN = 0
OCTAVE_MAX = 30  # inclusive; 2**30 fits int32, 2**31 would not
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
assert len(RSQRT_FLAT) == N_OCTAVES * BUCKETS_PER_OCTAVE == 992

OCT_LOWER = [2 ** o for o in range(OCTAVE_MIN, OCTAVE_MAX + 1)]  # tiny ROM, addressed by o
assert OCT_LOWER[-1] < 2 ** 31


def rsqrt_addr(vpe_fp):
    """Mirrors the actual circuit algorithm bit-for-bit, not a clean
    math.log2() shortcut - so this Python reference and the in-game
    combinators are computing the SAME integer steps, not just numerically
    close ones:
      o = count of thresholds 2,4,8,...,2^30 that vpe_fp meets or exceeds
          (30 independent >= comparisons on a shared broadcast wire, summed -
          same "N parallel deciders + shared collector" pattern already
          proven by the classifier's argmax/detector layers, not a new
          mechanism - chosen over a serial "find highest set bit" shift-chain
          specifically to avoid a NEW multi-step timing-sync dependency,
          the exact class of bug that cost several sessions on the matmul
          block, Reshenie 22-26)
      oct_lower = 2^o, looked up from a 31-word ROM addressed by o (same
          build_addressed_rom mechanism as every other ROM in this project)
      diff = vpe_fp - oct_lower                    (in [0, oct_lower))
      half_lower = oct_lower // 32                 (0 for o<5 - Factorio's
          own documented div-by-zero-safe convention, /0 -> 0, makes this
          branch-free: tiny variances just saturate at subbucket 0, a graceful
          precision loss in the regime Reshenie 16/20 already found least
          sensitive to LUT coarseness, not a hazard)
      s = diff // half_lower, clamped to [0,31]     (0 when half_lower==0)
      addr = o*32 + s
    """
    o = 0
    for k in range(OCTAVE_MIN, OCTAVE_MAX):  # 30 thresholds: 2^(k+1) for k=0..29
        if vpe_fp >= 2 ** (k + 1):
            o += 1
    o = min(o, OCTAVE_MAX)
    oct_lower = OCT_LOWER[o - OCTAVE_MIN]
    diff = vpe_fp - oct_lower
    half_lower = oct_lower // 32  # exact (oct_lower is a power of 2) when o>=5, else 0
    s = trunc_div(diff, half_lower) if half_lower != 0 else 0
    s = max(0, min(BUCKETS_PER_OCTAVE - 1, s))
    return (o - OCTAVE_MIN) * BUCKETS_PER_OCTAVE + s


def layernorm_fixed(x_real, gamma_real, beta_real, verbose=True):
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

    if verbose:
        print(f"x_fp={x_fp}")
        print(f"sum_fp={sum_fp} mean_fp={mean_fp}")
        print(f"sumsq_fp={sumsq_fp} esq_fp={esq_fp} var_fp={var_fp} vpe_fp={vpe_fp}")
        print(f"rsqrt addr={addr} (octave {OCTAVE_MIN + addr // BUCKETS_PER_OCTAVE}, subbucket {addr % BUCKETS_PER_OCTAVE}) rsqrt_fp={rsqrt_fp}")
        print(f"out_fp={out_fp}")
        print(f"out_real={[v / SCALE for v in out_fp]}")
    return dict(x_fp=x_fp, mean_fp=mean_fp, var_fp=var_fp, vpe_fp=vpe_fp, rsqrt_addr=addr, rsqrt_fp=rsqrt_fp, out_fp=out_fp)


if __name__ == "__main__":
    print(f"OCTAVE_MIN={OCTAVE_MIN} (range {OCTAVE_MIN}..{OCTAVE_MIN + N_OCTAVES - 1}), table words={len(RSQRT_FLAT)}")
    print(f"x0_real={x0_real}")
    result = layernorm_fixed(x0_real, gamma_real, beta_real)
    out_real = [v / SCALE for v in result["out_fp"]]
    print(f"\nExpected (H1_POS0, already proven live in matmul block) = {H1_POS0}")
    print(f"Got (LUT fixed-point pipeline)                          = {out_real}")
    max_err = max(abs(a - b) for a, b in zip(out_real, H1_POS0))
    print(f"max abs error = {max_err:.4f}")

    with open("stage2_layernorm_ref.json", "w") as f:
        json.dump({
            "SCALE": SCALE, "N_IN": N_IN, "EPS_SCALED": EPS_SCALED,
            "OCTAVE_MIN": OCTAVE_MIN, "N_OCTAVES": N_OCTAVES, "BUCKETS_PER_OCTAVE": BUCKETS_PER_OCTAVE,
            "rsqrt_table": RSQRT_FLAT,
            "x_real": x0_real, "gamma_real": gamma_real, "beta_real": beta_real,
            "x_fp": result["x_fp"], "mean_fp": result["mean_fp"], "var_fp": result["var_fp"],
            "vpe_fp": result["vpe_fp"], "rsqrt_addr": result["rsqrt_addr"], "rsqrt_fp": result["rsqrt_fp"],
            "out_fp": result["out_fp"], "expected_H1_POS0": H1_POS0,
        }, f, indent=2)
    print("\nSaved stage2_layernorm_ref.json")
