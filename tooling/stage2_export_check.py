"""
Reshenie 16 used a random-init model as a proxy (had to - nothing was
trained yet). Now that stage2_weights.json is real (Reshenie 5-ish
discipline: verify against the actual thing, not a proxy), redo that
check on the REAL trained model - actual weight magnitudes, actual
activation statistics - to pick a real SCALE and a real lookup-table
bucket count, not a guessed one.
"""

import json

import numpy as np

with open("stage2_weights.json") as f:
    ckpt = json.load(f)

W = {k: np.array(v) for k, v in ckpt["weights"].items()}
DIM, LAYERS, HEADS, FFN, CONTEXT = ckpt["dim"], ckpt["layers"], ckpt["heads"], ckpt["ffn"], ckpt["context"]
VOCAB = ckpt["vocab"]
VOCAB_SIZE = len(VOCAB)
HEAD_DIM = DIM // HEADS
EPS = 1e-5

print(f"Loaded checkpoint at step {ckpt['step']}: dim={DIM} layers={LAYERS} heads={HEADS} ffn={FFN} vocab={VOCAB_SIZE}")

w_abs_max = max(np.abs(v).max() for v in W.values())
w_abs_p99 = np.percentile(np.concatenate([np.abs(v).flatten() for v in W.values()]), 99)
print(f"Trained weight magnitude: max={w_abs_max:.4f}  p99={w_abs_p99:.4f}")

ln_variances = []
softmax_inputs = []


def layernorm(x, w, b, record=True):
    mean = x.mean(axis=-1, keepdims=True)
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    if record:
        ln_variances.append(var.flatten())
    return (x - mean) / np.sqrt(var + EPS) * w + b


def softmax_causal(scores, record=True):
    T = scores.shape[-1]
    mask = np.triu(np.ones((T, T), dtype=bool), k=1)
    scores = np.where(mask, -1e9, scores)
    shifted = scores - scores.max(axis=-1, keepdims=True)
    if record:
        softmax_inputs.append(shifted[~mask].flatten())
    e = np.exp(shifted)
    return e / e.sum(axis=-1, keepdims=True)


def attention(x, blk):
    T, C = x.shape
    qkv = x @ blk["qkv.weight"].T + blk["qkv.bias"]
    q, k, v = qkv[:, :DIM], qkv[:, DIM:2 * DIM], qkv[:, 2 * DIM:]
    q = q.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
    k = k.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
    v = v.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
    scores = (q @ k.transpose(0, 2, 1)) / np.sqrt(HEAD_DIM)
    attn = np.stack([softmax_causal(scores[h]) for h in range(HEADS)])
    out = (attn @ v).transpose(1, 0, 2).reshape(T, C)
    return out @ blk["proj.weight"].T + blk["proj.bias"]


def forward(idx):
    T = len(idx)
    x = W["tok_emb.weight"][idx] + W["pos_emb.weight"][:T]
    for l in range(LAYERS):
        blk = {k.split(f"blocks.{l}.")[1]: v for k, v in W.items() if k.startswith(f"blocks.{l}.")}
        x = x + attention(layernorm(x, blk["ln1.weight"], blk["ln1.bias"]), blk)
        h = layernorm(x, blk["ln2.weight"], blk["ln2.bias"])
        h = np.maximum(0, h @ blk["fc1.weight"].T + blk["fc1.bias"])
        x = x + h @ blk["fc2.weight"].T + blk["fc2.bias"]
    x = layernorm(x, W["ln_f.weight"], W["ln_f.bias"])
    logits = x @ W["tok_emb.weight"].T
    shifted = logits - logits.max(axis=-1, keepdims=True)
    softmax_inputs.append(shifted.flatten())
    return logits


rng = np.random.default_rng(0)
for _ in range(50):
    idx = rng.integers(0, VOCAB_SIZE, size=CONTEXT)
    forward(idx)

all_var = np.concatenate(ln_variances)
all_smax = np.concatenate(softmax_inputs)
print(f"\nReal-model LayerNorm variance: min={all_var.min():.5f} max={all_var.max():.4f} p50={np.percentile(all_var,50):.4f} p99={np.percentile(all_var,99):.4f}")
print(f"Real-model softmax input (post max-subtract): min={all_smax.min():.2f} p1={np.percentile(all_smax,1):.2f} p50={np.percentile(all_smax,50):.2f}")

for SCALE in (100, 1000):
    var_scaled = all_var * SCALE ** 2
    fits = var_scaled.max() < 2 ** 31
    print(f"\nSCALE={SCALE}: variance range in fixed-point [{var_scaled.min():.0f}, {var_scaled.max():.0f}] "
          f"(int32 max {2**31-1:,}) -> {'FITS' if fits else 'OVERFLOWS'}")


# ---------------- lookup tables (same design as Reshenie 16) ----------------
def lut_rsqrt(x, buckets_per_octave, octave_range=(-20, 20)):
    x = np.maximum(np.asarray(x, dtype=np.float64), 1e-12)
    o = np.floor(np.log2(x)).astype(int)
    o = np.clip(o, octave_range[0], octave_range[1] - 1)
    frac = x / (2.0 ** o)
    s = np.clip(np.floor((frac - 1) * buckets_per_octave).astype(int), 0, buckets_per_octave - 1)
    rep = (1 + s / buckets_per_octave) * (2.0 ** o)
    return 1.0 / np.sqrt(rep)


def lut_exp(x, n_buckets, x_min):
    x = np.asarray(x, dtype=np.float64)
    width = -x_min / n_buckets
    idx = np.floor(-x / width).astype(int)
    return np.where(idx >= n_buckets, 0.0, np.exp(-(idx + 0.5) * width))


def forward_lut(idx, rsqrt_fn, exp_fn):
    T = len(idx)

    def ln(x, w, b):
        mean = x.mean(axis=-1, keepdims=True)
        var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
        return (x - mean) * rsqrt_fn(var + EPS) * w + b

    def sm(scores):
        Tn = scores.shape[-1]
        mask = np.triu(np.ones((Tn, Tn), dtype=bool), k=1)
        scores = np.where(mask, -1e9, scores)
        shifted = scores - scores.max(axis=-1, keepdims=True)
        shifted = np.where(mask, -1e9, shifted)
        e = exp_fn(shifted)
        e = np.where(mask, 0.0, e)
        return e / np.maximum(e.sum(axis=-1, keepdims=True), 1e-12)

    def attn(x, blk):
        qkv = x @ blk["qkv.weight"].T + blk["qkv.bias"]
        q, k, v = qkv[:, :DIM], qkv[:, DIM:2 * DIM], qkv[:, 2 * DIM:]
        q = q.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
        k = k.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
        v = v.reshape(T, HEADS, HEAD_DIM).transpose(1, 0, 2)
        scores = (q @ k.transpose(0, 2, 1)) / np.sqrt(HEAD_DIM)
        a = np.stack([sm(scores[h]) for h in range(HEADS)])
        out = (a @ v).transpose(1, 0, 2).reshape(T, DIM)
        return out @ blk["proj.weight"].T + blk["proj.bias"]

    x = W["tok_emb.weight"][idx] + W["pos_emb.weight"][:T]
    for l in range(LAYERS):
        blk = {k.split(f"blocks.{l}.")[1]: v for k, v in W.items() if k.startswith(f"blocks.{l}.")}
        x = x + attn(ln(x, blk["ln1.weight"], blk["ln1.bias"]), blk)
        h = ln(x, blk["ln2.weight"], blk["ln2.bias"])
        h = np.maximum(0, h @ blk["fc1.weight"].T + blk["fc1.bias"])
        x = x + h @ blk["fc2.weight"].T + blk["fc2.bias"]
    x = ln(x, W["ln_f.weight"], W["ln_f.bias"])
    return x @ W["tok_emb.weight"].T


print(f"\n=== Real-model accuracy: exact math vs lookup-table nonlinearities ===")
for bpo, nexp, xmin in ((8, 64, -16.0), (16, 128, -32.0), (32, 256, -32.0)):
    flips, n = 0, 40
    for i in range(n):
        idx = np.random.default_rng(200 + i).integers(0, VOCAB_SIZE, size=CONTEXT)
        true_logits = forward(idx)
        lut_logits = forward_lut(idx, lambda x: lut_rsqrt(x, bpo), lambda x: lut_exp(x, nexp, xmin))
        if true_logits[-1].argmax() != lut_logits[-1].argmax():
            flips += 1
    print(f"rsqrt {bpo}/octave, exp {nexp} buckets (range {xmin} to 0): argmax flipped {flips}/{n} ({100*flips/n:.0f}%)")
