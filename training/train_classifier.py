"""
Trains the full classifier: bag-of-syllables (250 known 3-letter chunks,
see build_vocab.py) -> hidden layer (ReLU) -> 50 topic classes (49 reused/
new intents + fallback). Same architecture family as demo_train.py, just
at real scale.

Train/val split is done by PHRASE, not by transliteration variant - all
variants of the same phrase stay on the same side of the split, so val
accuracy reflects generalization to phrasing, not just memorized variants
of something already seen.
"""

import json

import numpy as np

from translit import generate_variants

np.random.seed(0)

with open("../data/intents_cardputer.json", encoding="utf-8") as f:
    cardputer = json.load(f)
with open("../data/intents_new_factorio.json", encoding="utf-8") as f:
    factorio_new = json.load(f)
with open("vocab_syllables.json", encoding="utf-8") as f:
    VOCAB = json.load(f)

all_intents = cardputer["intents"] + factorio_new["intents"]
CLASSES = [i["name"] for i in all_intents] + ["fallback"]
SYLLABLE_LENS = (3,)  # must match build_vocab.py - pure 3-grams outperformed (2,3,4) mix
VARIANTS_PER_PHRASE = 16  # more transliteration diversity - was 8, doubled to fight overfitting
VAL_FRACTION = 0.2

syl_index = {s: i for i, s in enumerate(VOCAB)}


def featurize(text: str) -> np.ndarray:
    padded = f" {text.lower()} "
    vec = np.zeros(len(VOCAB), dtype=np.float64)
    for L in SYLLABLE_LENS:
        for i in range(len(padded) - L + 1):
            idx = syl_index.get(padded[i : i + L])
            if idx is not None:
                vec[idx] += 1
    # L1-normalize: short phrases ("да", "пока") only ever fire 2-4 detectors
    # total, giving near-zero-magnitude input that gets dominated by output
    # bias regardless of WHICH detectors fired - confirmed via confusion
    # analysis (short phrases collapsing into whichever class has the
    # highest bias, "what_doing", rather than a semantically similar one).
    # Normalizing so short and long phrases have comparable total magnitude
    # forces the network to rely on the PATTERN of active syllables, not
    # how many total syllables exist.
    total = vec.sum()
    if total > 0:
        vec = vec / total
    return vec


# gather (phrase, class_idx) pairs, then split by phrase before generating variants
rng = np.random.RandomState(0)
train_X, train_y, val_X, val_y = [], [], [], []

phrase_class_pairs = []
for ci, intent in enumerate(all_intents):
    for ex in intent["examples"]:
        phrase_class_pairs.append((ex, ci))
for ex in cardputer["fallback"]["examples"]:
    phrase_class_pairs.append((ex, len(all_intents)))

rng.shuffle(phrase_class_pairs)
n_val_phrases = int(len(phrase_class_pairs) * VAL_FRACTION)
val_phrases = set(p for p, _ in phrase_class_pairs[:n_val_phrases])

for phrase, ci in phrase_class_pairs:
    variants = generate_variants(phrase, VARIANTS_PER_PHRASE, seed=hash(phrase) % 10000)
    target = (val_X, val_y) if phrase in val_phrases else (train_X, train_y)
    for v in variants:
        target[0].append(featurize(v))
        target[1].append(ci)

train_X, train_y = np.array(train_X), np.array(train_y)
val_X, val_y = np.array(val_X), np.array(val_y)
print(f"Classes: {len(CLASSES)} | Train examples: {len(train_X)} | Val examples: {len(val_X)}")

n_in, n_hidden, n_out = len(VOCAB), 32, len(CLASSES)

W1 = np.random.randn(n_in, n_hidden) * (1.0 / np.sqrt(n_in))
b1 = np.zeros(n_hidden)
W2 = np.random.randn(n_hidden, n_out) * (1.0 / np.sqrt(n_hidden))
b2 = np.zeros(n_out)


def forward(X):
    h_pre = X @ W1 + b1
    h = np.maximum(0, h_pre)
    logits = h @ W2 + b2
    return h_pre, h, logits


def accuracy(X, y):
    _, _, logits = forward(X)
    return (np.argmax(logits, axis=1) == y).mean()


n_steps = 12000
batch_size = 128
# Adam - plain SGD was oscillating late in training (loss bouncing instead
# of settling) rather than cleanly converging, consistent with underfitting
# from unstable optimization, not just too few steps.
beta1, beta2, eps = 0.9, 0.999, 1e-8
mW1, vW1 = np.zeros_like(W1), np.zeros_like(W1)
mb1, vb1 = np.zeros_like(b1), np.zeros_like(b1)
mW2, vW2 = np.zeros_like(W2), np.zeros_like(W2)
mb2, vb2 = np.zeros_like(b2), np.zeros_like(b2)
base_lr = 0.003
L2 = 0.0004
DROPOUT_P = 0.15  # fraction of active input features randomly zeroed per step

for step in range(n_steps):
    idx = rng.randint(0, len(train_X), size=batch_size)
    X, y = train_X[idx], train_y[idx]
    drop_mask = rng.random_sample(X.shape) > DROPOUT_P
    X = X * drop_mask

    h_pre = X @ W1 + b1
    h = np.maximum(0, h_pre)
    logits = h @ W2 + b2
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)

    grad_logits = probs.copy()
    grad_logits[np.arange(len(y)), y] -= 1
    grad_logits /= len(y)

    grad_W2 = h.T @ grad_logits + L2 * W2
    grad_b2 = grad_logits.sum(axis=0)
    grad_h = grad_logits @ W2.T
    grad_h_pre = grad_h * (h_pre > 0)
    grad_W1 = X.T @ grad_h_pre + L2 * W1
    grad_b1 = grad_h_pre.sum(axis=0)

    t = step + 1
    lr = base_lr * (0.5 ** (step // 4000))  # halve every 4000 steps
    for param, grad, m, v in (
        (W1, grad_W1, mW1, vW1), (b1, grad_b1, mb1, vb1),
        (W2, grad_W2, mW2, vW2), (b2, grad_b2, mb2, vb2),
    ):
        m[:] = beta1 * m + (1 - beta1) * grad
        v[:] = beta2 * v + (1 - beta2) * (grad ** 2)
        m_hat = m / (1 - beta1 ** t)
        v_hat = v / (1 - beta2 ** t)
        param -= lr * m_hat / (np.sqrt(v_hat) + eps)

    if step % 1000 == 0 or step == n_steps - 1:
        loss = -np.log(probs[np.arange(len(y)), y] + 1e-9).mean()
        print(f"step {step}: loss={loss:.4f} train_acc={accuracy(train_X, train_y):.3f} val_acc={accuracy(val_X, val_y):.3f}")

print(f"\nFinal: train_acc={accuracy(train_X, train_y):.3f} val_acc={accuracy(val_X, val_y):.3f}")

weights = {
    "vocab": VOCAB,
    "classes": CLASSES,
    "W1": W1.tolist(),
    "b1": b1.tolist(),
    "W2": W2.tolist(),
    "b2": b2.tolist(),
}
with open("classifier_weights.json", "w", encoding="utf-8") as f:
    json.dump(weights, f, ensure_ascii=False)
print("Saved classifier_weights.json")
