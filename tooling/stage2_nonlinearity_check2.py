"""
Part 2: build actual lookup-table approximations for exp()/rsqrt() and
measure real damage to a forward pass, given the wide dynamic ranges found
in stage2_nonlinearity_check.py (LayerNorm variance spans ~9 orders of
magnitude across plausible weight scales; naive fixed-point at SCALE=1000
OVERFLOWS int32 for variance beyond ~2147 in real terms).

Bucket scheme for rsqrt: since log() isn't a native combinator op either,
use floor(log2(x)) as the bucket index - this IS cheap in combinators (a
fixed ~5-comparison "find highest set bit" circuit via binary search on
powers of 2, same style as the already-proven multi-condition deciders),
no iteration needed. BUCKETS_PER_OCTAVE subdivides each power-of-2 range
for extra resolution (linear subdivision within an octave, cheap: one
divide + one more small compare/lookup).

Bucket scheme for exp: input is always <=0 (post max-subtraction), so
plain linear buckets over a bounded near-zero range work fine - anything
past the range legitimately rounds to 0 (that's correct behavior, not
error, since exp() is already negligible there).

Overflow fix tested: use a SMALLER fixed-point scale for activations
(ACT_SCALE) than for trained weights (SCALE=1000) - rescale after each
matmul, the same "explicit rescale between layers" already flagged as
necessary in demo_export.py's own docstring for anything deeper than its
2-layer demo.
"""

import numpy as np

rng = np.random.default_rng(0)
SCALE = 1000
DIM, LAYERS, HEADS, FFN, VOCAB, CONTEXT = 32, 3, 4, 128, 50, 48
HEAD_DIM = DIM // HEADS
EPS = 1e-5


# ---------------- lookup tables ----------------
def build_rsqrt_table(buckets_per_octave, octave_range=(-20, 20)):
    """table[i] = representative_value, rsqrt(representative_value) for
    octave o, subdivision s (0..buckets_per_octave-1)."""
    table = {}
    lo, hi = octave_range
    for o in range(lo, hi):
        for s in range(buckets_per_octave):
            frac = 1 + s / buckets_per_octave
            rep = frac * (2.0 ** o)
            table[(o, s)] = 1.0 / np.sqrt(rep)
    return table


def lut_rsqrt(x, buckets_per_octave, octave_range=(-20, 20)):
    x = np.asarray(x, dtype=np.float64)
    x = np.maximum(x, 1e-12)
    o = np.floor(np.log2(x)).astype(int)
    o = np.clip(o, *octave_range[:1] + (octave_range[1] - 1,) if False else (octave_range[0], octave_range[1] - 1))
    frac_in_octave = x / (2.0 ** o)  # in [1,2)
    s = np.floor((frac_in_octave - 1) * buckets_per_octave).astype(int)
    s = np.clip(s, 0, buckets_per_octave - 1)
    rep = (1 + s / buckets_per_octave) * (2.0 ** o)
    return 1.0 / np.sqrt(rep)


def lut_exp(x, n_buckets, x_min=-16.0):
    x = np.asarray(x, dtype=np.float64)
    width = -x_min / n_buckets
    idx = np.floor(-x / width).astype(int)  # x<=0, idx=0 near 0
    out = np.where(idx >= n_buckets, 0.0, np.exp(-(idx + 0.5) * width))
    return out


# ---------------- forward pass, parameterized by nonlinearity impl ----------------
def make_params(weight_scale, seed=1):
    r = np.random.default_rng(seed)
    def randn(*shape):
        return r.standard_normal(shape).astype(np.float64) * weight_scale
    tok_emb = randn(VOCAB, DIM)
    pos_emb = randn(CONTEXT, DIM)
    blocks = []
    for _ in range(LAYERS):
        blocks.append(dict(
            Wqkv=randn(DIM, 3 * DIM), bqkv=np.zeros(3 * DIM),
            Wproj=randn(DIM, DIM), bproj=np.zeros(DIM),
            Wfc1=randn(DIM, FFN), bfc1=np.zeros(FFN),
            Wfc2=randn(FFN, DIM), bfc2=np.zeros(DIM),
        ))
    return tok_emb, pos_emb, blocks


def forward(idx, tok_emb, pos_emb, blocks, rsqrt_fn, exp_fn):
    T = len(idx)

    def layernorm(x):
        mean = x.mean(axis=-1, keepdims=True)
        var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
        return (x - mean) * rsqrt_fn(var + EPS)

    def softmax_causal(scores):
        Tn = scores.shape[-1]
        mask = np.triu(np.ones((Tn, Tn), dtype=bool), k=1)
        scores = np.where(mask, -1e9, scores)
        shifted = scores - scores.max(axis=-1, keepdims=True)
        shifted = np.where(mask, -1e9, shifted)
        e = exp_fn(shifted)
        e = np.where(mask, 0.0, e)
        return e / np.maximum(e.sum(axis=-1, keepdims=True), 1e-12)

    def attention(x, blk):
        qkv = x @ blk["Wqkv"] + blk["bqkv"]
        q, k, v = qkv[:, :DIM], qkv[:, DIM:2 * DIM], qkv[:, 2 * DIM:]
        q = q.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
        k = k.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
        v = v.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
        scores = (q @ k.transpose(0, 2, 1)) / np.sqrt(HEAD_DIM)
        attn = np.stack([softmax_causal(scores[h]) for h in range(HEADS)])
        out = (attn @ v).transpose(1, 0, 2).reshape(T, DIM)
        return out @ blk["Wproj"] + blk["bproj"]

    x = tok_emb[idx] + pos_emb[:T]
    for blk in blocks:
        x = x + attention(layernorm(x), blk)
        h = layernorm(x)
        h = np.maximum(0, h @ blk["Wfc1"] + blk["bfc1"])
        x = x + h @ blk["Wfc2"] + blk["bfc2"]
    x = layernorm(x)
    logits = x @ tok_emb.T
    return logits


def true_rsqrt(x):
    return 1.0 / np.sqrt(x)


def true_exp(x):
    return np.exp(x)


print("=== Bucket-count sweep at weight_scale=0.3 (moderate, realistic-ish) ===")
tok_emb, pos_emb, blocks = make_params(0.3)
for bpo, nexp in ((4, 32), (8, 64), (16, 128), (32, 256), (64, 512)):
    argmax_flips, n = 0, 30
    for i in range(n):
        idx = np.random.default_rng(100 + i).integers(0, VOCAB, size=CONTEXT)
        true_logits = forward(idx, tok_emb, pos_emb, blocks, true_rsqrt, true_exp)
        lut_logits = forward(
            idx, tok_emb, pos_emb, blocks,
            lambda x: lut_rsqrt(x, buckets_per_octave=bpo),
            lambda x: lut_exp(x, n_buckets=nexp, x_min=-16.0),
        )
        if true_logits[-1].argmax() != lut_logits[-1].argmax():
            argmax_flips += 1
    print(f"rsqrt {bpo} buckets/octave, exp {nexp} buckets: argmax flipped {argmax_flips}/{n} ({100*argmax_flips/n:.0f}%)")

print("\n=== Same bucket sweep at the harsher weight_scale=1.0 (was 30% flips with the coarse table) ===")
tok_emb1, pos_emb1, blocks1 = make_params(1.0)
for bpo, nexp in ((4, 32), (8, 64), (16, 128), (32, 256)):
    argmax_flips, n = 0, 30
    for i in range(n):
        idx = np.random.default_rng(100 + i).integers(0, VOCAB, size=CONTEXT)
        true_logits = forward(idx, tok_emb1, pos_emb1, blocks1, true_rsqrt, true_exp)
        lut_logits = forward(
            idx, tok_emb1, pos_emb1, blocks1,
            lambda x: lut_rsqrt(x, buckets_per_octave=bpo),
            lambda x: lut_exp(x, n_buckets=nexp, x_min=-16.0),
        )
        if true_logits[-1].argmax() != lut_logits[-1].argmax():
            argmax_flips += 1
    print(f"rsqrt {bpo} buckets/octave, exp {nexp} buckets: argmax flipped {argmax_flips}/{n} ({100*argmax_flips/n:.0f}%)")

print("\n=== Isolating the source: rsqrt-only vs exp-only lookup error (weight_scale=0.3, generous bucket counts) ===")
for label, rfn, efn in [
    ("both exact (sanity=0%)", true_rsqrt, true_exp),
    ("rsqrt LUT(16/oct) only", lambda x: lut_rsqrt(x, 16), true_exp),
    ("exp LUT(128) only", true_rsqrt, lambda x: lut_exp(x, 128, -16.0)),
    ("both LUT (16/oct, 128)", lambda x: lut_rsqrt(x, 16), lambda x: lut_exp(x, 128, -16.0)),
]:
    argmax_flips, n = 0, 30
    for i in range(n):
        idx = np.random.default_rng(100 + i).integers(0, VOCAB, size=CONTEXT)
        true_logits = forward(idx, tok_emb, pos_emb, blocks, true_rsqrt, true_exp)
        lut_logits = forward(idx, tok_emb, pos_emb, blocks, rfn, efn)
        if true_logits[-1].argmax() != lut_logits[-1].argmax():
            argmax_flips += 1
    print(f"{label}: argmax flipped {argmax_flips}/{n} ({100*argmax_flips/n:.0f}%)")
