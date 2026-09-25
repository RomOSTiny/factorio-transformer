"""
Finds cross-topic near-duplicate examples: pairs of example phrases
assigned to DIFFERENT topics whose syllable feature vectors are highly
similar (cosine similarity). These are genuine data conflicts - the model
can't distinguish them because they really do look almost the same.
"""

import json

import numpy as np

from translit import transliterate_once
import random

with open("../data/intents_cardputer.json", encoding="utf-8") as f:
    cardputer = json.load(f)
with open("../data/intents_new_factorio.json", encoding="utf-8") as f:
    factorio_new = json.load(f)
with open("vocab_syllables.json", encoding="utf-8") as f:
    VOCAB = json.load(f)

all_intents = cardputer["intents"] + factorio_new["intents"]
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


examples = []  # (phrase, topic)
for intent in all_intents:
    for ex in intent["examples"]:
        examples.append((ex, intent["name"]))
for ex in cardputer["fallback"]["examples"]:
    examples.append((ex, "fallback"))

rng = random.Random(0)
feats = np.array([featurize(transliterate_once(p, rng)) for p, _ in examples])
norms = np.linalg.norm(feats, axis=1, keepdims=True)
norms[norms == 0] = 1
unit = feats / norms
sim = unit @ unit.T

pairs = []
n = len(examples)
for i in range(n):
    for j in range(i + 1, n):
        if examples[i][1] != examples[j][1] and sim[i, j] > 0.5:
            pairs.append((sim[i, j], examples[i][0], examples[i][1], examples[j][0], examples[j][1]))

pairs.sort(key=lambda x: -x[0])
print(f"Found {len(pairs)} cross-topic pairs with cosine similarity > 0.55\n")
for s, p1, t1, p2, t2 in pairs[:60]:
    print(f"{s:.2f}  '{p1}' [{t1}]  <->  '{p2}' [{t2}]")
