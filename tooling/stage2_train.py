"""
Stage 2 training: standard autoregressive LM training (cross-entropy,
AdamW), CPU (dev machine, per PROJECT.md Reshenie 4 - home PC with the
RTX 4060 not available yet). 40,832-param model, 17.9M training tokens
(roneneldan/TinyStories slice, stage2_data_prep.py) - about 438 tokens
per parameter, generous for a model this small, so this run doesn't need
to exhaust the data, just needs enough steps to converge.

Saves stage2_weights.json (same format spirit as the classifier's
demo_weights.json/classifier_weights.json - plain nested lists, ready for
a later export script) plus periodic checkpoints so a long run surviving
across background-task boundaries isn't wasted if interrupted.
"""

import json
import time

import numpy as np
import torch
import torch.nn.functional as F

from stage2_model import TinyGenModel, CONTEXT
from stage2_tokenizer import VOCAB_SIZE, decode

torch.manual_seed(0)

data = np.load("stage2_data.npy")
n_val = len(data) // 20
train_data = torch.from_numpy(data[:-n_val].astype(np.int64))
val_data = torch.from_numpy(data[-n_val:].astype(np.int64))
print(f"Train tokens: {len(train_data):,}  Val tokens: {len(val_data):,}")

model = TinyGenModel(VOCAB_SIZE)
print(f"Params: {model.num_params():,}")
opt = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=0.01)

BATCH_SIZE = 128
STEPS = 8000
EVAL_EVERY = 500


def get_batch(data_src):
    ix = torch.randint(0, len(data_src) - CONTEXT - 1, (BATCH_SIZE,))
    x = torch.stack([data_src[i:i + CONTEXT] for i in ix])
    y = torch.stack([data_src[i + 1:i + CONTEXT + 1] for i in ix])
    return x, y


@torch.no_grad()
def eval_loss(data_src, n_batches=10):
    model.eval()
    losses = []
    for _ in range(n_batches):
        x, y = get_batch(data_src)
        logits = model(x)
        loss = F.cross_entropy(logits.reshape(-1, VOCAB_SIZE), y.reshape(-1))
        losses.append(loss.item())
    model.train()
    return float(np.mean(losses))


@torch.no_grad()
def sample(prompt="one day", n=100):
    model.eval()
    from stage2_tokenizer import encode
    ids = encode(prompt)
    ids = ids[-CONTEXT:]
    for _ in range(n):
        x = torch.tensor([ids[-CONTEXT:]], dtype=torch.long)
        logits = model(x)[0, -1]
        probs = F.softmax(logits, dim=-1)
        nxt = torch.multinomial(probs, 1).item()
        ids.append(nxt)
    model.train()
    return decode(ids)


def save_checkpoint(step):
    weights = {name: p.detach().numpy().tolist() for name, p in model.named_parameters()}
    out = {
        "step": step,
        "vocab": list("abcdefghijklmnopqrstuvwxyz .,!?'\"-\n"),
        "dim": 32, "layers": 3, "heads": 4, "ffn": 128, "context": CONTEXT,
        "weights": weights,
    }
    with open("stage2_weights.json", "w") as f:
        json.dump(out, f)


print(f"\nTraining: {STEPS} steps, batch={BATCH_SIZE}, context={CONTEXT}")
t0 = time.time()
model.train()
for step in range(1, STEPS + 1):
    x, y = get_batch(train_data)
    logits = model(x)
    loss = F.cross_entropy(logits.reshape(-1, VOCAB_SIZE), y.reshape(-1))
    opt.zero_grad()
    loss.backward()
    opt.step()

    if step % EVAL_EVERY == 0 or step == 1:
        vloss = eval_loss(val_data)
        elapsed = time.time() - t0
        rate = step / elapsed
        eta = (STEPS - step) / rate if rate > 0 else 0
        print(f"step {step:>5}/{STEPS}  train_loss={loss.item():.3f}  val_loss={vloss:.3f}  "
              f"elapsed={elapsed:.0f}s  eta={eta:.0f}s  ({rate:.2f} steps/s)")
        save_checkpoint(step)

print(f"\nDone in {time.time()-t0:.0f}s. Final val_loss={eval_loss(val_data):.3f}")
print("\n=== Sample generation ===")
for p in ["one day", "the little", "she said"]:
    print(f"{p!r} -> {sample(p, 150)!r}")
