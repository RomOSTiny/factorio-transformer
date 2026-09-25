"""
Numeric reference for the Sequencer (Этап 2, механика 4 — control unit that
chains the three already-closed mechanics into one full forward pass).

Unlike stage2_attention_ref.py (which only worked out ONE position's
attention, just enough to validate the softmax/lookup math), this file
computes the ENTIRE smoke-model forward pass end to end, fixed-point,
every stage a Factorio circuit will actually need to reproduce:

  embed -> ln1 (per pos) -> qkv matmul -> attention (per pos, growing
  window, KV over ALL positions) -> proj matmul -> residual1 -> ln2 (per
  pos) -> fc1 matmul + relu -> fc2 matmul -> residual2 -> ln_f (per pos)
  -> logits matmul -> argmax (last position only, next-token prediction)

Same test case as stage2_attention_ref.py: stage2_smoke_weights.json
(dim=4, 1 layer, 1 head, ffn=8, context=3, vocab=4), tokens=[0,2]. This is
the ground truth the Sequencer circuit's own dump must match bit-exact,
the same role stage2_attention_ref.json played for the Attention block.

Conventions reused verbatim from stage2_attention_ref.py (already proven
live 08.09.2026): SCALE=100, q()/trunc_div() fixed-point helpers,
layernorm_fixed (rsqrt octave-ROM), matmul_fixed (bias folded in as
input index N_IN, one rescale at the end), exp_lut_fixed (flat linear
bucket ROM) for softmax. Nothing new numerically here except stitching
the stages together and adding fc1/relu/fc2/residuals/logits, which are
all just matmul_fixed + plain fixed-point add (same SCALE both sides, no
rescale needed) + a max(0,.) that is scale-invariant since SCALE>0.
"""
import json
import math

with open("stage2_smoke_weights.json") as f:
    ref = json.load(f)

SCALE = 100
DIM = ref["dim"]
HEADS = ref["heads"]
HEAD_DIM = DIM // HEADS
FFN = ref["ffn"]
VOCAB = ref["vocab_size"]
EPS_SCALED = 1
TOKENS = ref["tokens"]
T = len(TOKENS)

N_BUCKETS = 200
X_MIN = -16.0
WIDTH = -X_MIN / N_BUCKETS
WIDTH_FP = round(SCALE * WIDTH)
assert WIDTH_FP == SCALE * WIDTH

# float reference values, stage2_smoke_ref.py, for a sanity cross-check
# (not bit-exact target -- fixed-point rounds differently at each stage --
# just used to catch a wrong-stage/wrong-sign class of bug early)
EXPECTED_NEXT_TOKEN = 1  # filled in after running stage2_smoke_ref.py once; see __main__ check


def q(x):
    return int(round(x * SCALE))


def trunc_div(a, b):
    """Factorio's arithmetic-combinator division: truncates toward zero."""
    aa, bb = abs(a), abs(b)
    r = aa // bb
    return -r if (a < 0) != (b < 0) else r


# ---- rsqrt table, verbatim from stage2_attention_ref.py / layernorm ----
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


def layernorm_fixed(x_fp, gamma_fp, beta_fp):
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
    raw = sum(a_fp[i] * b_fp[i] for i in range(len(a_fp)))
    return trunc_div(trunc_div(raw, SCALE), divisor)


def forward_fixed(verbose=True):
    tok_emb, pos_emb = ref["tok_emb"], ref["pos_emb"]
    Wqkv, bqkv = ref["Wqkv"], ref["bqkv"]
    Wproj, bproj = ref["Wproj"], ref["bproj"]
    Wfc1, bfc1 = ref["Wfc1"], ref["bfc1"]
    Wfc2, bfc2 = ref["Wfc2"], ref["bfc2"]
    ones, zeros = [1.0] * DIM, [0.0] * DIM

    # ---- embed: x[pos] = tok_emb[tok] + pos_emb[pos], done directly in
    # fixed point (both tables quantized by q(), then summed -- no matmul
    # needed, embedding is a straight ROM-address lookup + add) ----
    x_fp = []
    for i, t in enumerate(TOKENS):
        x_fp.append([q(tok_emb[t][d]) + q(pos_emb[i][d]) for d in range(DIM)])
    if verbose:
        print(f"embed x_fp={x_fp}")

    # ---- ln1 + qkv, every position (KV-cache: k_fp/v_fp kept for ALL
    # positions, q_fp only needed at the position being processed but kept
    # for all here since we compute every position's attention anyway) ----
    h1_fp, q_fp, k_fp, v_fp = [], [], [], []
    for i in range(T):
        h1_fp.append(layernorm_fixed(x_fp[i], [q(g) for g in ones], [q(b) for b in zeros]))
        qkv_fp = matmul_fixed(h1_fp[i], Wqkv, bqkv, 3 * DIM)
        q_fp.append(qkv_fp[:DIM])
        k_fp.append(qkv_fp[DIM:2 * DIM])
        v_fp.append(qkv_fp[2 * DIM:])
    if verbose:
        print(f"h1_fp={h1_fp}")
        print(f"q_fp={q_fp} k_fp={k_fp} v_fp={v_fp}")

    # ---- attention, growing window: position pos attends to 0..pos ----
    assert math.isqrt(HEAD_DIM) ** 2 == HEAD_DIM
    sqrt_head_dim = math.isqrt(HEAD_DIM)
    attn_out_fp = []
    attn_dbg = []
    for pos in range(T):
        scores_fp = [dot_scaled_fixed(q_fp[pos], k_fp[tt], sqrt_head_dim) for tt in range(pos + 1)]
        max_score_fp = max(scores_fp)
        shifted_fp = [s - max_score_fp for s in scores_fp]
        exp_fp = [exp_lut_fixed(s) for s in shifted_fp]
        sum_exp_fp = sum(exp_fp)
        weights_fp = [trunc_div(e * SCALE, sum_exp_fp) for e in exp_fp]
        out_fp = []
        for d in range(DIM):
            raw = sum(weights_fp[tt] * v_fp[tt][d] for tt in range(pos + 1))
            out_fp.append(trunc_div(raw, SCALE))
        attn_out_fp.append(out_fp)
        attn_dbg.append(dict(scores_fp=scores_fp, weights_fp=weights_fp, out_fp=out_fp))
        if verbose:
            print(f"  [attn pos={pos}] scores={scores_fp} weights={weights_fp} out={out_fp}")

    # ---- output projection + residual 1 ----
    proj_fp = [matmul_fixed(attn_out_fp[i], Wproj, bproj, DIM) for i in range(T)]
    x2_fp = [[x_fp[i][d] + proj_fp[i][d] for d in range(DIM)] for i in range(T)]
    if verbose:
        print(f"proj_fp={proj_fp}")
        print(f"x2_fp={x2_fp}")

    # ---- ln2 + fc1(relu) + fc2 + residual 2 ----
    h2_fp = [layernorm_fixed(x2_fp[i], [q(g) for g in ones], [q(b) for b in zeros]) for i in range(T)]
    fc1_fp = [[max(0, v) for v in matmul_fixed(h2_fp[i], Wfc1, bfc1, FFN)] for i in range(T)]
    fc2_fp = [matmul_fixed(fc1_fp[i], Wfc2, bfc2, DIM) for i in range(T)]
    x3_fp = [[x2_fp[i][d] + fc2_fp[i][d] for d in range(DIM)] for i in range(T)]
    if verbose:
        print(f"h2_fp={h2_fp}")
        print(f"fc1_fp={fc1_fp}")
        print(f"fc2_fp={fc2_fp}")
        print(f"x3_fp={x3_fp}")

    # ---- final layernorm + logits (last position only -- next-token
    # prediction only ever needs the last position's logits) ----
    xf_fp = [layernorm_fixed(x3_fp[i], [q(g) for g in ones], [q(b) for b in zeros]) for i in range(T)]
    last = T - 1
    logits_fp = []
    for vi in range(VOCAB):
        raw = sum(xf_fp[last][d] * q(tok_emb[vi][d]) for d in range(DIM))
        logits_fp.append(trunc_div(raw, SCALE))
    next_token = int(max(range(VOCAB), key=lambda i: logits_fp[i]))
    if verbose:
        print(f"xf_fp={xf_fp}")
        print(f"logits_fp={logits_fp}")
        print(f"next_token={next_token}")

    return dict(
        x_fp=x_fp, h1_fp=h1_fp, q_fp=q_fp, k_fp=k_fp, v_fp=v_fp,
        attn_dbg=attn_dbg, attn_out_fp=attn_out_fp,
        proj_fp=proj_fp, x2_fp=x2_fp, h2_fp=h2_fp, fc1_fp=fc1_fp, fc2_fp=fc2_fp, x3_fp=x3_fp,
        xf_fp=xf_fp, logits_fp=logits_fp, next_token=next_token,
    )


if __name__ == "__main__":
    print(f"SCALE={SCALE} DIM={DIM} FFN={FFN} VOCAB={VOCAB} T={T} tokens={TOKENS}")
    result = forward_fixed()

    # cross-check against the float reference's own argmax by re-running it
    import subprocess, sys, re
    proc = subprocess.run([sys.executable, "stage2_smoke_ref.py"], capture_output=True, text=True, cwd=".")
    mfloat = re.search(r"next token \(argmax of last position\) = (\d+)", proc.stdout)
    float_next = int(mfloat.group(1)) if mfloat else None
    print(f"\nfixed-point next_token={result['next_token']}  float-reference next_token={float_next}")
    if float_next is not None and float_next != result['next_token']:
        print("WARNING: fixed-point argmax disagrees with float reference -- expected occasionally "
              "(quantization can flip a close argmax, same class of effect as Решение 16), "
              "but check logits_fp margins below before assuming it's fine.")
        print(f"logits_fp={result['logits_fp']}")

    with open("stage2_sequencer_ref.json", "w") as f:
        json.dump({
            "SCALE": SCALE, "DIM": DIM, "FFN": FFN, "VOCAB": VOCAB, "HEAD_DIM": HEAD_DIM,
            "N_BUCKETS": N_BUCKETS, "X_MIN": X_MIN, "WIDTH_FP": WIDTH_FP,
            "exp_table": EXP_TABLE, "rsqrt_table": RSQRT_FLAT,
            "tokens": TOKENS,
            **{k: v for k, v in result.items()},
        }, f, indent=2)
    print("Saved stage2_sequencer_ref.json")
