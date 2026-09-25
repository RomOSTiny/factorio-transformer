"""
Loads the trained classifier + val split logic (same seed = same split) and
reports which topic PAIRS are most confused with each other, and which
individual training examples are most likely causing cross-topic conflicts
(near-duplicate phrasing assigned to different classes). Data-driven input
for deciding what to merge/clean, not guesswork.
"""

import json
from collections import Counter

import numpy as np

from translit import generate_variants

with open("../data/intents_cardputer.json", encoding="utf-8") as f:
    cardputer = json.load(f)
with open("../data/intents_new_factorio.json", encoding="utf-8") as f:
    factorio_new = json.load(f)
with open("vocab_syllables.json", encoding="utf-8") as f:
    VOCAB = json.load(f)
with open("classifier_weights.json", encoding="utf-8") as f:
    weights = json.load(f)

all_intents = cardputer["intents"] + factorio_new["intents"]
CLASSES = weights["classes"]
W1, b1, W2, b2 = (np.array(weights[k]) for k in ("W1", "b1", "W2", "b2"))
SYL_LEN = 3
syl_index = {s: i for i, s in enumerate(VOCAB)}


def featurize(text):
    padded = f" {text.lower()} "
    vec = np.zeros(len(VOCAB))
    for i in range(len(padded) - SYL_LEN + 1):
        idx = syl_index.get(padded[i : i + SYL_LEN])
        if idx is not None:
            vec[idx] += 1
    return vec


def predict(X):
    h = np.maximum(0, X @ W1 + b1)
    logits = h @ W2 + b2
    return np.argmax(logits, axis=1)


# rebuild the exact same val split (same seed/logic as train_classifier.py)
rng = np.random.RandomState(0)
phrase_class_pairs = []
for ci, intent in enumerate(all_intents):
    for ex in intent["examples"]:
        phrase_class_pairs.append((ex, ci))
for ex in cardputer["fallback"]["examples"]:
    phrase_class_pairs.append((ex, len(all_intents)))
rng.shuffle(phrase_class_pairs)
n_val = int(len(phrase_class_pairs) * 0.2)
val_phrases = set(p for p, _ in phrase_class_pairs[:n_val])

confusion = Counter()
wrong_examples = []
for phrase, true_ci in phrase_class_pairs:
    if phrase not in val_phrases:
        continue
    variants = generate_variants(phrase, 8, seed=hash(phrase) % 10000)
    X = np.array([featurize(v) for v in variants])
    preds = predict(X)
    for p in preds:
        if p != true_ci:
            confusion[(CLASSES[true_ci], CLASSES[p])] += 1
    if (preds != true_ci).mean() > 0.5:
        wrong_examples.append((phrase, CLASSES[true_ci], CLASSES[preds[0]]))

print("Top 25 most confused topic pairs (true -> predicted, count):")
for (true_c, pred_c), count in confusion.most_common(25):
    print(f"  {true_c:20s} -> {pred_c:20s}  {count}")

print(f"\n{len(wrong_examples)} val phrases misclassified in >50% of their variants:")
for phrase, true_c, pred_c in wrong_examples:
    print(f"  '{phrase}'  [{true_c}] -> predicted [{pred_c}]")
