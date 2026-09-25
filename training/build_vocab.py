"""
Merges the 37 reused Cardputer topics + 13 new Factorio topics, generates
transliteration variants, and picks a syllable vocabulary via GREEDY
MAXIMUM COVERAGE: repeatedly pick the syllable that covers the most
examples not yet covered by any already-picked syllable.

First attempt used a pure "discriminative concentration" score (favors
syllables highly concentrated in one topic) - checked empirically after
training plateaued at ~64% train accuracy despite plenty of model
capacity, and found 34% of examples (206/604) had ZERO active features
under that vocabulary: the concentration score picked narrow, rare
syllables at the expense of covering most phrases at all. Coverage has to
come first - a discriminative-but-absent feature is worth nothing.
"""

import json
from collections import Counter

from translit import generate_variants

with open("../data/intents_cardputer.json", encoding="utf-8") as f:
    cardputer = json.load(f)
with open("../data/intents_new_factorio.json", encoding="utf-8") as f:
    factorio_new = json.load(f)

all_intents = cardputer["intents"] + factorio_new["intents"]
fallback = cardputer["fallback"]

print(f"Topics: {len(all_intents)} + 1 fallback = {len(all_intents) + 1}")

VARIANTS_PER_PHRASE = 4
SYLLABLE_LENS = (3,)  # tried mixing in (2,3,4) - val accuracy got WORSE (35.5% vs
# 42.4%), 2-grams are too generic/low-signal and diluted the vocab budget.
# Pure 3-grams performed best empirically - kept as a tuple for the ngrams()
# helper below, not because mixing is the goal.
VOCAB_SIZE = 300  # detection cost roughly VOCAB_SIZE * ~48 positions, see PROJECT.md budget

# unique (padded_variant) strings, not (variant, topic) - coverage is about
# covering PHRASES, topic label doesn't matter for vocabulary selection
all_variants = []
for intent in all_intents:
    for example in intent["examples"]:
        for v in generate_variants(example, VARIANTS_PER_PHRASE, seed=hash(example) % 10000):
            all_variants.append(f" {v.lower()} ")
for example in fallback["examples"]:
    for v in generate_variants(example, VARIANTS_PER_PHRASE, seed=hash(example) % 10000):
        all_variants.append(f" {v.lower()} ")

print(f"Total phrase variants: {len(all_variants)}")


def ngrams(padded):
    for L in SYLLABLE_LENS:
        for i in range(len(padded) - L + 1):
            yield padded[i : i + L]


# syllable -> set of variant indices it appears in
syllable_to_variants = {}
for vi, padded in enumerate(all_variants):
    seen_here = set(ngrams(padded))
    for syl in seen_here:
        syllable_to_variants.setdefault(syl, set()).add(vi)

print(f"Distinct syllables observed (lengths {SYLLABLE_LENS}): {len(syllable_to_variants)}")

# greedy max coverage
uncovered = set(range(len(all_variants)))
chosen = []
# work on a mutable copy so we can prune candidates whose remaining
# contribution drops to zero (cheap optimization, doesn't change the result)
candidates = {s: set(v) for s, v in syllable_to_variants.items()}

# Phase 1: greedy set cover for "at least 1 active feature" on every phrase.
while uncovered:
    best_syl, best_gain = None, -1
    for syl, vs in candidates.items():
        gain = len(vs & uncovered)
        if gain > best_gain:
            best_syl, best_gain = syl, gain
    if best_gain <= 0:
        break
    chosen.append(best_syl)
    uncovered -= candidates[best_syl]
    del candidates[best_syl]

phase1_size = len(chosen)
print(f"Phase 1 (full coverage): {phase1_size} syllables, {len(uncovered)} variants left uncovered")

# Phase 2: "at least 1 feature" is a weak signal - keep adding syllables
# past full coverage so most phrases get SEVERAL active features, not
# just one, up to the combinator budget. Just take remaining candidates
# by raw frequency (richest signal first) - coverage objective is already
# satisfied, no need for the expensive greedy-gain recompute anymore.
remaining_budget = VOCAB_SIZE - phase1_size
remaining_sorted = sorted(candidates.items(), key=lambda kv: -len(kv[1]))
for syl, _ in remaining_sorted[:remaining_budget]:
    chosen.append(syl)

print(f"Chosen vocabulary size: {len(chosen)} (phase 1: {phase1_size}, phase 2 top-up: {len(chosen) - phase1_size})")

# sanity check: average/median active features per phrase with the final vocab
final_index = {s: i for i, s in enumerate(chosen)}
counts_per_phrase = []
for padded in all_variants:
    n = sum(1 for g in ngrams(padded) if g in final_index)
    counts_per_phrase.append(n)
import statistics

print(f"Active features per phrase - mean: {statistics.mean(counts_per_phrase):.2f}, median: {statistics.median(counts_per_phrase)}, min: {min(counts_per_phrase)}, zero-count phrases: {sum(1 for c in counts_per_phrase if c == 0)}")

with open("vocab_syllables.json", "w", encoding="utf-8") as f:
    json.dump(chosen, f, ensure_ascii=False, indent=2)
print("Saved vocab_syllables.json")
