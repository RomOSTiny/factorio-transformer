"""
Stage 2 generative model - decoder-only transformer, same shape family as
Cardputer Path A (path_a/training/model.py: pre-norm blocks, tied
embedding/output weights, learned positional embeddings, causal
self-attention) but much smaller, per PROJECT.md Reshenie 13/17's entity
budget (config B: dim=32, layers=3, heads=4, ffn=128, target ~100-200K
circuit entities once exported).

Trained in plain float32 here - the fixed-point/int32-overflow concerns
found in Reshenie 16 (LayerNorm variance, exp() range) are an EXPORT-time
concern (choosing SCALE and any per-layer rescale from the ACTUAL trained
weight magnitudes), not a training-time one. Keep them in mind for
stage2_export.py, not here.
"""

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

DIM = 32
LAYERS = 3
HEADS = 4
FFN = 128
CONTEXT = 48
HEAD_DIM = DIM // HEADS


class Block(nn.Module):
    def __init__(self, dim=DIM, heads=HEADS, ffn=FFN):
        super().__init__()
        self.heads = heads
        self.head_dim = dim // heads
        self.ln1 = nn.LayerNorm(dim)
        self.qkv = nn.Linear(dim, 3 * dim, bias=True)
        self.proj = nn.Linear(dim, dim, bias=True)
        self.ln2 = nn.LayerNorm(dim)
        self.fc1 = nn.Linear(dim, ffn, bias=True)
        self.fc2 = nn.Linear(ffn, dim, bias=True)

    def forward(self, x, causal_mask):
        B, T, C = x.shape
        h = self.ln1(x)
        qkv = self.qkv(h)
        q, k, v = qkv.split(C, dim=-1)
        q = q.view(B, T, self.heads, self.head_dim).transpose(1, 2)
        k = k.view(B, T, self.heads, self.head_dim).transpose(1, 2)
        v = v.view(B, T, self.heads, self.head_dim).transpose(1, 2)
        scores = (q @ k.transpose(-2, -1)) / math.sqrt(self.head_dim)
        scores = scores.masked_fill(causal_mask, float("-inf"))
        attn = F.softmax(scores, dim=-1)
        out = (attn @ v).transpose(1, 2).reshape(B, T, C)
        x = x + self.proj(out)
        h = self.ln2(x)
        h = F.relu(self.fc1(h))  # ReLU, not GELU - matches the classifier's
        # already-proven decider-based ReLU pattern; GELU has no cheap
        # combinator equivalent and wasn't in the Reshenie 13 plan.
        x = x + self.fc2(h)
        return x


class TinyGenModel(nn.Module):
    def __init__(self, vocab_size, dim=DIM, layers=LAYERS, heads=HEADS, ffn=FFN, context=CONTEXT):
        super().__init__()
        self.context = context
        self.tok_emb = nn.Embedding(vocab_size, dim)
        self.pos_emb = nn.Embedding(context, dim)
        self.blocks = nn.ModuleList([Block(dim, heads, ffn) for _ in range(layers)])
        self.ln_f = nn.LayerNorm(dim)
        # tied embedding/output weights - same choice as Cardputer Path A,
        # halves the biggest single weight matrix's storage cost

    def forward(self, idx):
        B, T = idx.shape
        pos = torch.arange(T, device=idx.device)
        x = self.tok_emb(idx) + self.pos_emb(pos)
        mask = torch.triu(torch.ones(T, T, dtype=torch.bool, device=idx.device), diagonal=1)
        for blk in self.blocks:
            x = blk(x, mask)
        x = self.ln_f(x)
        logits = x @ self.tok_emb.weight.T
        return logits

    def num_params(self):
        return sum(p.numel() for p in self.parameters())


if __name__ == "__main__":
    from stage2_tokenizer import VOCAB_SIZE

    m = TinyGenModel(VOCAB_SIZE)
    print(f"Params: {m.num_params():,}")
    for name, p in m.named_parameters():
        print(f"  {name:30s} {tuple(p.shape)}")
    x = torch.randint(0, VOCAB_SIZE, (2, CONTEXT))
    out = m(x)
    print(f"Forward OK: input {tuple(x.shape)} -> output {tuple(out.shape)}")
