"""
Stage 2 data prep: download a slice of TinyStories (roneneldan/TinyStories -
short, simple English stories, purpose-built for training tiny language
models, confirmed reachable from this machine), character-tokenize with
stage2_tokenizer.py, save as a single numpy uint8 array for fast reloading
during training. Vocab is 35 (fits in uint8 trivially).

Why TinyStories and not a generic corpus: the model here is ~40K
parameters (PROJECT.md Reshenie 13/17 target, config B) - a tiny fraction
of even Cardputer's 271K demo. Generic web/book text needs far more
capacity to model; TinyStories' deliberately simple vocabulary and short
sentences give a tiny model an actual fighting chance at learning
something coherent, rather than guaranteed noise on a corpus it has no
hope of fitting.

Only a SLICE is used (N_STORIES), not the full ~2.1M-story dataset -
CPU training on this dev machine (Решение 4: real capacity work happens
on the home PC later), so keeping the first pass small and fast to
iterate on matters more than dataset size right now.
"""

import numpy as np
from datasets import load_dataset

from stage2_tokenizer import decode, encode, VOCAB_SIZE

N_STORIES = 20000  # slice size for the first CPU training pass

print(f"Streaming {N_STORIES} stories from roneneldan/TinyStories...")
ds = load_dataset("roneneldan/TinyStories", split="train", streaming=True)

all_ids = []
n = 0
for row in ds:
    ids = encode(row["text"] + "\n")
    all_ids.extend(ids)
    n += 1
    if n >= N_STORIES:
        break
    if n % 2000 == 0:
        print(f"  {n}/{N_STORIES} stories, {len(all_ids)} chars so far")

arr = np.array(all_ids, dtype=np.uint8)
np.save("stage2_data.npy", arr)
print(f"\nSaved stage2_data.npy: {len(arr)} tokens from {n} stories, vocab_size={VOCAB_SIZE}")
print(f"First 200 chars decoded:\n{decode(arr[:200].tolist())!r}")
