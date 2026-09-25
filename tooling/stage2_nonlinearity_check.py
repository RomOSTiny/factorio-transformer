"""
Stage 2: does the lookup-table approximation for exp()/rsqrt() (the one
real gap identified in PROJECT.md Reshenie 13 - no native sqrt/exp on
combinators) actually work numerically, on realistic values, in the
32-bit-signed-integer fixed-point world combinators live in? This is
checked BEFORE spending any effort on scale, per the user's own
instruction to fix architecture correctness first (see Reshenie 16 in
PROJECT.md).

Method: build a small, UNTRAINED (random-init) transformer matching the
project's own reference shapes (Cardputer path_a style: pre-norm blocks,
tied embeddings, causal self-attention), run real forward passes to see
what LayerNorm variance and post-max-subtraction softmax logits actually
look like in practice - not guessed - then simulate the SAME forward pass
using a lookup-table exp()/rsqrt() in place of the real functions, and
measure the actual damage: value error, whether argmax over final logits
changes, whether attention weighting changes.

Pure numpy, no autograd needed (only a forward pass with random weights).
Un-trained weights are deliberately used - training happens later either
way (weights come in as data, same as the classifier), and random-init
activations are, if anything, LESS well-behaved (more spread out) than a
trained model's, so this is a conservative (harder) test, not optimistic.
"""

import numpy as np

rng = np.random.default_rng(0)

SCALE = 1000  # same fixed-point scale used throughout this project

# ---- Config B from PROJECT.md Reshenie 13 (mid-size candidate) ----
DIM, LAYERS, HEADS, FFN, VOCAB, CONTEXT = 32, 3, 4, 128, 50, 48
HEAD_DIM = DIM // HEADS


def randn(*shape, scale=0.02):
    return rng.standard_normal(shape).astype(np.float64) * scale


class Block:
    def __init__(self):
        self.ln1_w, self.ln1_b = np.ones(DIM), np.zeros(DIM)
        self.ln2_w, self.ln2_b = np.ones(DIM), np.zeros(DIM)
        self.Wqkv, self.bqkv = randn(DIM, 3 * DIM), np.zeros(3 * DIM)
        self.Wproj, self.bproj = randn(DIM, DIM), np.zeros(DIM)
        self.Wfc1, self.bfc1 = randn(DIM, FFN), np.zeros(FFN)
        self.Wfc2, self.bfc2 = randn(FFN, DIM), np.zeros(DIM)


tok_emb = randn(VOCAB, DIM)
pos_emb = randn(CONTEXT, DIM)
blocks = [Block() for _ in range(LAYERS)]
ln_f_w, ln_f_b = np.ones(DIM), np.zeros(DIM)

ln_variances = []
softmax_inputs = []
EPS = 1e-5


def layernorm(x, w, b):
    mean = x.mean(axis=-1, keepdims=True)
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    ln_variances.append(var.flatten())
    return (x - mean) / np.sqrt(var + EPS) * w + b


def softmax_causal(scores):
    T = scores.shape[-1]
    mask = np.triu(np.ones((T, T), dtype=bool), k=1)
    scores = np.where(mask, -1e9, scores)
    shifted = scores - scores.max(axis=-1, keepdims=True)
    finite = shifted[~mask]
    softmax_inputs.append(finite.flatten())
    e = np.exp(shifted)
    return e / e.sum(axis=-1, keepdims=True)


def attention(x, blk):
    T, C = x.shape
    qkv = x @ blk.Wqkv + blk.bqkv
    q, k, v = qkv[:, :DIM], qkv[:, DIM:2 * DIM], qkv[:, 2 * DIM:]
    q = q.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
    k = k.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
    v = v.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
    scores = (q @ k.transpose(0, 2, 1)) / np.sqrt(HEAD_DIM)
    attn = np.stack([softmax_causal(scores[h]) for h in range(HEADS)])
    out = (attn @ v).transpose(1, 0, 2).reshape(T, C)
    return out @ blk.Wproj + blk.bproj


def forward(idx):
    T = len(idx)
    x = tok_emb[idx] + pos_emb[:T]
    for blk in blocks:
        x = x + attention(layernorm(x, blk.ln1_w, blk.ln1_b), blk)
        h = layernorm(x, blk.ln2_w, blk.ln2_b)
        h = np.maximum(0, h @ blk.Wfc1 + blk.bfc1)
        x = x + h @ blk.Wfc2 + blk.bfc2
    x = layernorm(x, ln_f_w, ln_f_b)
    logits = x @ tok_emb.T
    shifted = logits - logits.max(axis=-1, keepdims=True)
    softmax_inputs.append(shifted.flatten())
    return logits


def run_sweep(weight_scale):
    global tok_emb, pos_emb, blocks, ln_variances, softmax_inputs
    rng2 = np.random.default_rng(1)

    def randn2(*shape):
        return rng2.standard_normal(shape).astype(np.float64) * weight_scale

    tok_emb = randn2(VOCAB, DIM)
    pos_emb = randn2(CONTEXT, DIM)
    blocks = []
    for _ in range(LAYERS):
        b = Block.__new__(Block)
        b.ln1_w, b.ln1_b = np.ones(DIM), np.zeros(DIM)
        b.ln2_w, b.ln2_b = np.ones(DIM), np.zeros(DIM)
        b.Wqkv, b.bqkv = randn2(DIM, 3 * DIM), np.zeros(3 * DIM)
        b.Wproj, b.bproj = randn2(DIM, DIM), np.zeros(DIM)
        b.Wfc1, b.bfc1 = randn2(DIM, FFN), np.zeros(FFN)
        b.Wfc2, b.bfc2 = randn2(FFN, DIM), np.zeros(DIM)
        blocks.append(b)
    ln_variances, softmax_inputs = [], []
    for _ in range(20):
        idx = rng2.integers(0, VOCAB, size=CONTEXT)
        forward(idx)
    return np.concatenate(ln_variances), np.concatenate(softmax_inputs)


print("=== Sweep: how much does weight scale (proxy for 'how trained/confident the model is') widen the ranges? ===")
worst_var_max, worst_smax_min = 0, 0
for wscale in (0.02, 0.1, 0.3, 1.0, 2.0):
    var, smax_in = run_sweep(wscale)
    print(f"weight_scale={wscale:>4}: LN var [{var.min():.5f}, {var.max():.4f}]  "
          f"softmax-in [{smax_in.min():.2f}, {smax_in.max():.2f}]  (p1={np.percentile(smax_in,1):.2f})")
    worst_var_max = max(worst_var_max, var.max())
    worst_smax_min = min(worst_smax_min, smax_in.min())

print(f"\nWorst observed across sweep: LN var max={worst_var_max:.4f}, softmax-in min={worst_smax_min:.2f}")
print("(untrained random weights only - a real trained model could still exceed this; design range below is padded generously beyond the observed worst case, not fit tightly to it)")
