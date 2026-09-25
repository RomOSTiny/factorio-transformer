"""
Smoke-test reference for the full generative-model circuit (Reshenie 21).
Tiny hand-sized transformer (dim=4, 1 layer, 1 head, ffn=8, context=3,
vocab=4) - NOT the real trained model, just small enough that every
intermediate value can be printed and checked against the circuit's own
dump, same role demo_train.py/demo_export.py played for the classifier.

Weights are small fixed integers (not trained) chosen so fixed-point
arithmetic (SCALE=100 here, smaller than the real model's 1000 since
everything is tiny) stays easy to eyeball, not for any modeling reason.
"""

import numpy as np

np.random.seed(0)
DIM, LAYERS, HEADS, FFN, CONTEXT, VOCAB = 4, 1, 1, 8, 3, 4
HEAD_DIM = DIM // HEADS
SCALE = 100
EPS_SCALED = 1  # eps in fixed-point units, negligible vs real variances here

# small integer-ish weights, real numbers for the Python reference (export
# script will quantize by SCALE later - here we just need ground truth)
rng = np.random.default_rng(42)
tok_emb = rng.integers(-3, 4, size=(VOCAB, DIM)).astype(np.float64) * 0.1
pos_emb = rng.integers(-3, 4, size=(CONTEXT, DIM)).astype(np.float64) * 0.1
ln1_w, ln1_b = np.ones(DIM), np.zeros(DIM)
ln2_w, ln2_b = np.ones(DIM), np.zeros(DIM)
Wqkv = rng.integers(-3, 4, size=(DIM, 3 * DIM)).astype(np.float64) * 0.1
bqkv = np.zeros(3 * DIM)
Wproj = rng.integers(-3, 4, size=(DIM, DIM)).astype(np.float64) * 0.1
bproj = np.zeros(DIM)
Wfc1 = rng.integers(-3, 4, size=(DIM, FFN)).astype(np.float64) * 0.1
bfc1 = np.zeros(FFN)
Wfc2 = rng.integers(-3, 4, size=(FFN, DIM)).astype(np.float64) * 0.1
bfc2 = np.zeros(DIM)
ln_f_w, ln_f_b = np.ones(DIM), np.zeros(DIM)

TOKENS = [0, 2]  # 2-token prompt, will generate token 3 (index 2, 0-based position)


def layernorm(x, w, b, tag):
    mean = x.mean()
    var = ((x - mean) ** 2).mean()
    out = (x - mean) / np.sqrt(var + 1e-5) * w + b
    print(f"    [{tag}] mean={mean:.4f} var={var:.4f} out={out.round(4).tolist()}")
    return out


def forward_verbose(tokens):
    T = len(tokens)
    print(f"\n=== Forward pass, tokens={tokens} ===")
    x = np.stack([tok_emb[t] + pos_emb[i] for i, t in enumerate(tokens)])
    print(f"  embed: x=\n{x.round(4)}")

    h1 = np.stack([layernorm(x[i], ln1_w, ln1_b, f"ln1_pos{i}") for i in range(T)])
    qkv = h1 @ Wqkv + bqkv
    q, k, v = qkv[:, :DIM], qkv[:, DIM:2 * DIM], qkv[:, 2 * DIM:]
    print(f"  q=\n{q.round(4)}\n  k=\n{k.round(4)}\n  v=\n{v.round(4)}")

    attn_out = np.zeros((T, DIM))
    for pos in range(T):
        scores = np.array([np.dot(q[pos], k[t]) / np.sqrt(HEAD_DIM) for t in range(pos + 1)])
        shifted = scores - scores.max()
        e = np.exp(shifted)
        w_ = e / e.sum()
        out = sum(w_[t] * v[t] for t in range(pos + 1))
        attn_out[pos] = out
        print(f"    [attn pos={pos}] scores={scores.round(4).tolist()} weights={w_.round(4).tolist()} out={out.round(4).tolist()}")

    proj_out = attn_out @ Wproj + bproj
    x2 = x + proj_out
    print(f"  x2 (after residual 1)=\n{x2.round(4)}")

    h2 = np.stack([layernorm(x2[i], ln2_w, ln2_b, f"ln2_pos{i}") for i in range(T)])
    fc1_out = np.maximum(0, h2 @ Wfc1 + bfc1)
    fc2_out = fc1_out @ Wfc2 + bfc2
    x3 = x2 + fc2_out
    print(f"  x3 (after residual 2)=\n{x3.round(4)}")

    xf = np.stack([layernorm(x3[i], ln_f_w, ln_f_b, f"lnf_pos{i}") for i in range(T)])
    logits = xf @ tok_emb.T
    print(f"  logits=\n{logits.round(4)}")
    next_token = int(logits[-1].argmax())
    print(f"  next token (argmax of last position) = {next_token}")
    return next_token


if __name__ == "__main__":
    nxt = forward_verbose(TOKENS)
    print(f"\n=== Result: prompt {TOKENS} -> next token {nxt} ===")

    weights = {
        "dim": DIM, "layers": LAYERS, "heads": HEADS, "ffn": FFN, "context": CONTEXT, "vocab_size": VOCAB,
        "tokens": TOKENS, "expected_next_token": nxt,
        "tok_emb": tok_emb.tolist(), "pos_emb": pos_emb.tolist(),
        "Wqkv": Wqkv.tolist(), "bqkv": bqkv.tolist(),
        "Wproj": Wproj.tolist(), "bproj": bproj.tolist(),
        "Wfc1": Wfc1.tolist(), "bfc1": bfc1.tolist(),
        "Wfc2": Wfc2.tolist(), "bfc2": bfc2.tolist(),
    }
    import json
    with open("stage2_smoke_weights.json", "w") as f:
        json.dump(weights, f, indent=2)
    print("\nSaved stage2_smoke_weights.json")
