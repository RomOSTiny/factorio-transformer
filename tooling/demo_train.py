"""
Tiny demo classifier - proves the FULL pipeline (multi-layer + ReLU + argmax),
not just multiplication like proof_of_pipeline.py did. See ../PROJECT.md.

4 keyword inputs -> 2 ReLU hidden neurons -> 3 output classes -> argmax.
Toy, hand-separable task, trained for real (not hand-picked weights) so the
export step proves "real trained weights survive the trip into the game".
"""

import json

import numpy as np

np.random.seed(0)

KEYWORDS = ["hello", "bye", "how", "you"]  # -> signal-A, signal-B, signal-C, signal-D
CLASSES = ["greeting", "farewell", "question"]  # -> signal-0, signal-1, signal-2

# bag-of-keywords binary vectors -> class index
DATA = [
    ([1, 0, 0, 0], 0),
    ([1, 0, 0, 1], 0),
    ([0, 1, 0, 0], 1),
    ([0, 1, 0, 1], 1),
    ([0, 0, 1, 0], 2),
    ([0, 0, 0, 1], 2),
    ([0, 0, 1, 1], 2),
]

X = np.array([d[0] for d in DATA], dtype=np.float64)
y = np.array([d[1] for d in DATA], dtype=np.int64)

n_in, n_hidden, n_out = 4, 2, 3

W1 = np.random.randn(n_in, n_hidden) * 0.5
b1 = np.zeros(n_hidden)
W2 = np.random.randn(n_hidden, n_out) * 0.5
b2 = np.zeros(n_out)

lr = 0.1
for step in range(2000):
    h_pre = X @ W1 + b1
    h = np.maximum(0, h_pre)  # ReLU
    logits = h @ W2 + b2
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)

    grad_logits = probs.copy()
    grad_logits[np.arange(len(y)), y] -= 1
    grad_logits /= len(y)

    grad_W2 = h.T @ grad_logits
    grad_b2 = grad_logits.sum(axis=0)
    grad_h = grad_logits @ W2.T
    grad_h_pre = grad_h * (h_pre > 0)
    grad_W1 = X.T @ grad_h_pre
    grad_b1 = grad_h_pre.sum(axis=0)

    W1 -= lr * grad_W1
    b1 -= lr * grad_b1
    W2 -= lr * grad_W2
    b2 -= lr * grad_b2

    if step % 500 == 0:
        loss = -np.log(probs[np.arange(len(y)), y] + 1e-9).mean()
        print(f"step {step}: loss={loss:.4f}")

preds = np.argmax(X @ W1 + b1, axis=1)  # placeholder, real check below
h = np.maximum(0, X @ W1 + b1)
logits = h @ W2 + b2
preds = np.argmax(logits, axis=1)
acc = (preds == y).mean()
print(f"Train accuracy: {acc:.0%}")
for (vec, label), pred in zip(DATA, preds):
    print(f"  {vec} -> true={CLASSES[label]}, pred={CLASSES[pred]}")

weights = {
    "keywords": KEYWORDS,
    "classes": CLASSES,
    "W1": W1.tolist(),
    "b1": b1.tolist(),
    "W2": W2.tolist(),
    "b2": b2.tolist(),
}
with open("demo_weights.json", "w") as f:
    json.dump(weights, f, indent=2)
print("\nSaved demo_weights.json")
