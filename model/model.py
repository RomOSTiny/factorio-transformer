"""Standalone integer model matching the Factorio circuit.

6,393,344 parameters; 8 layers; 8 heads; width 256; FFN 1024;
256-character context; deterministic greedy character generation.
Requires Python 3.10+ and NumPy. Weights are loaded beside this file.

MIT License

Copyright (c) 2026 RomOSTiny

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from pathlib import Path
import argparse
import json
import math
import sys
import numpy as np

EXP_SC = 200000
ATT_OFF = 10 ** 8
LN_EPS_Q = 410
LN_NEWTON_ITERS = 4
LN_K_MAX = 15

def track(name, value):
    return value

def tdiv(a, b):
    """Factorio division: truncation toward zero (b > 0 or array)."""
    a = np.asarray(a, dtype=np.int64)
    q = np.abs(a) // np.abs(b)
    return np.where((a >= 0) == (np.asarray(b) > 0), q, -q)


# ---------------------------------------------------------------- weights

def load_float():
    path = Path(__file__).resolve().with_name("weights.npz")
    with np.load(path, allow_pickle=False) as archive:
        cfg = json.loads(str(archive["__cfg__"]))
        vocab = json.loads(str(archive["__vocab__"]))
        weights = {key: archive[key].copy() for key in archive.files if not key.startswith("__")}
    return cfg, vocab, weights


def qw(a):
    """Weight quantization of the engine: round(w * 1000) (float32 like their torch.round)."""
    return np.round(np.asarray(a, dtype=np.float32) * np.float32(1000)).astype(np.int64)


def qln(a):
    return np.round(np.asarray(a, dtype=np.float32) * np.float32(100)).astype(np.int64)


class IntModel:
    def __init__(self):
        self.cfg, self.vocab, P = load_float()
        c = self.cfg
        self.dim, self.layers, self.heads, self.ffn, self.ctx = c["dim"], c["layers"], c["heads"], c["ffn"], c["context"]
        self.hd = self.dim // self.heads
        self.emb_q = qw(P["tok_emb.weight"])                      # (V, D) in 0.001
        self.tok_u = tdiv(self.emb_q, 10)                         # trunc to 0.01
        self.pos_u = tdiv(qw(P["pos_emb.weight"]), 10)
        self.L = []
        for i in range(self.layers):
            p = f"blocks.{i}."
            self.L.append({n: (qw(P[p + n + ".weight"]).T.copy(), qw(P[p + n + ".bias"]))
                           for n in ("qkv", "proj", "fc1", "fc2")})
            for n in ("ln1", "ln2"):
                self.L[i][n] = (qln(P[p + n + ".weight"]), qln(P[p + n + ".bias"]))
        self.lnf = (qln(P["ln_f.weight"]), qln(P["ln_f.bias"]))
        self._att_consts()

    # ------------------------------------------------------------ attention exp table
    def _att_consts(self):
        c = 800.0 * math.sqrt(self.hd)          # one bucket (0.08 of d) in q.k units (1e-4)
        self.att_cut = int(math.floor(16e4 * math.sqrt(self.hd)))          # d <= 16
        nb = int(round(16 / 0.08))                                         # buckets 0..200
        # bucket b = #{thresholds < delta}; threshold b' = floor((b'+0.5) c)
        self.att_thr = np.array([math.floor((b + 0.5) * c) for b in range(nb)], dtype=np.int64)
        self.att_exp = np.array([int(round(EXP_SC * math.exp(-0.08 * b))) for b in range(nb + 1)], dtype=np.int64)

    def exp_of_delta(self, delta):
        b = np.searchsorted(self.att_thr, delta, side="left")
        e = self.att_exp[np.minimum(b, len(self.att_exp) - 1)]
        return np.where(delta <= self.att_cut, e, 0)

    def exp_steps(self):
        """Decider bank form: e(delta) = sum_t [delta <= T_t] * d_t (for the circuit generator)."""
        steps = []
        vals = list(self.att_exp)
        # interval of bucket b: delta in (thr[b-1], thr[b]]; last bucket ends at the cut
        ends = list(self.att_thr) + [self.att_cut]
        for b in range(len(vals)):
            nxt = vals[b + 1] if b + 1 < len(vals) else 0
            if vals[b] != nxt:
                steps.append((int(ends[b]), int(vals[b] - nxt)))
        return steps

    # ------------------------------------------------------------ blocks
    def linear(self, x, name, wb):
        W, b = wb
        acc = track("mm_acc/" + name, x @ W + b * 100)
        return tdiv(acc, 1000)

    def layernorm(self, x, gb):
        g, bta = gb
        x = np.asarray(x, dtype=np.int64)
        E = x.sum(-1, keepdims=True)
        track("ln_E", E)
        D = track("ln_D", self.dim * x - E)
        Er = np.floor_divide(E + 32, 64)                      # round(E/64), half up
        dq = 4 * x - Er
        Q = track("ln_Q", (dq * dq).sum(-1, keepdims=True)) + LN_EPS_Q
        s = np.array([[newton_isqrt(int(v))] for v in Q[:, 0]], dtype=np.int64)
        n2 = tdiv(track("ln_D250", D * 250), s)
        acc = track("ln_acc", n2 * g + bta * 1000)
        return tdiv(acc, 1000)

    def attention(self, q, k, v):
        T = q.shape[0]
        out = np.zeros_like(q)
        causal = np.tril(np.ones((T, T), dtype=bool))
        for h in range(self.heads):
            sl = slice(h * self.hd, (h + 1) * self.hd)
            raw = track("att_raw", q[:, sl] @ k[:, sl].T + ATT_OFF)
            raw_m = np.where(causal, raw, np.int64(-1))
            M = raw_m.max(-1, keepdims=True)
            delta = np.where(causal, M - raw, np.int64(1) << 40)
            e = self.exp_of_delta(delta)
            S = e.sum(-1, keepdims=True)
            w = (e * 10000) // S
            track("att_e1e4", e * 10000)
            acc = track("att_acc", w @ v[:, sl])
            out[:, sl] = tdiv(acc, 10000)
        return out

    def forward(self, tokens, trace=None):
        """trace: dict filled with every intermediate (T x n int arrays), keys like 'L0.h1', 'xf', 'logits'."""
        tokens = np.asarray(tokens, dtype=np.int64)
        T = len(tokens)
        x = self.tok_u[tokens] + self.pos_u[:T]
        D = self.dim
        tr = trace if trace is not None else {}
        tr["x0"] = x
        for i, Lw in enumerate(self.L):
            p = f"L{i}."
            h = tr[p + "h1"] = self.layernorm(x, Lw["ln1"])
            qkv = tr[p + "qkv"] = self.linear(h, "qkv", Lw["qkv"])
            att = tr[p + "att"] = self.attention(qkv[:, :D], qkv[:, D:2 * D], qkv[:, 2 * D:])
            pr = tr[p + "proj"] = self.linear(att, "proj", Lw["proj"])
            x = tr[p + "x2"] = x + pr
            track("x", x)
            h = tr[p + "h2"] = self.layernorm(x, Lw["ln2"])
            f = tr[p + "f1"] = np.maximum(0, self.linear(h, "fc1", Lw["fc1"]))
            f2 = tr[p + "f2"] = self.linear(f, "fc2", Lw["fc2"])
            x = tr[p + "x3"] = x + f2
            track("x", x)
        h = tr["xf"] = self.layernorm(x, self.lnf)
        lg = tr["logits"] = tdiv(track("logit_acc", h @ self.emb_q.T), 1000)
        return lg

    def generate(self, ids, max_new=200, stop_nl=True):
        ids = list(ids)
        new = []
        nl = self.vocab.index("\n")
        while len(ids) < self.ctx and len(new) < max_new:
            nxt = int(np.argmax(self.forward(ids)[-1]))       # np.argmax: first max = smaller index
            ids.append(nxt)
            new.append(nxt)
            if stop_nl and nxt == nl:
                break
        return new


def newton_isqrt(v, iters=LN_NEWTON_ITERS, k_max=LN_K_MAX):
    s = 1 + sum(2 ** (k - 1) for k in range(1, k_max + 1) if v >= 4 ** k)
    for _ in range(iters):
        t = v // s
        s = t // 2 + s // 2
    return s


import re
import unicodedata

import numpy as np

CHARS = list("abcdefghijklmnopqrstuvwxyz .,!?'\"-\n:")
VOCAB = len(CHARS)
STOI = {c: i for i, c in enumerate(CHARS)}
NEWLINE = STOI["\n"]
USER, BOT = "you: ", "bot: "

# Typographic variants of symbols that ARE in the alphabet: map, don't drop.
TYPO_MAP = str.maketrans({
    "‘": "'", "’": "'", "‛": "'", "`": "'", "´": "'", "\x92": "'", "\x91": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "\x93": '"', "\x94": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
    "\t": " ", "\r": "", " ": " ",
})
_DROP = re.compile(r"[^a-z .,!?'\"\-\n]")   # everything outside the alphabet, including ':'
_SPACES = re.compile(r" {2,}")
_NL_SPACES = re.compile(r" *\n *")

# byte -> token id lookup for fast encoding of already-normalized ASCII text
_LUT = np.full(256, 255, dtype=np.uint8)
for _i, _c in enumerate(CHARS):
    _LUT[ord(_c)] = _i


def normalize(text: str) -> str:
    """Lowercase, map typographic variants, strip accents, drop everything outside the alphabet (and ':')."""
    text = text.replace("…", "...").translate(TYPO_MAP).lower()
    if not text.isascii():
        text = unicodedata.normalize("NFKD", text)
    text = _DROP.sub("", text)
    text = _SPACES.sub(" ", text)
    text = _NL_SPACES.sub("\n", text)
    return text.strip(" ")


def encode_normalized(text: str) -> np.ndarray:
    """Encode text that is already in the alphabet (e.g. formatted dialogues). Raises on stray characters."""
    ids = _LUT[np.frombuffer(text.encode("ascii"), dtype=np.uint8)]
    if (ids == 255).any():
        raise ValueError(f"character outside the alphabet in {text[:80]!r}")
    return ids


def encode(text: str) -> list[int]:
    return encode_normalized(normalize(text)).tolist()


def decode(ids) -> str:
    return "".join(CHARS[i] for i in ids)


class IncrementalModel(IntModel):
    """The same integer operations with a KV cache, one new position at a time."""
    def reset(self):
        self.position = 0
        self.keys = np.empty((self.layers, self.ctx, self.dim), dtype=np.int64)
        self.values = np.empty_like(self.keys)

    def step(self, token):
        position = self.position
        if position >= self.ctx:
            raise ValueError("Context is full; reset before adding another character.")
        x = (self.tok_u[token] + self.pos_u[position])[None, :]
        D = self.dim
        for i, weights in enumerate(self.L):
            normalized = self.layernorm(x, weights["ln1"])
            qkv = self.linear(normalized, "qkv", weights["qkv"])
            q = qkv[:, :D]
            self.keys[i, position] = qkv[0, D:2 * D]
            self.values[i, position] = qkv[0, 2 * D:]
            attention = np.zeros_like(q)
            for head in range(self.heads):
                sl = slice(head * self.hd, (head + 1) * self.hd)
                raw = q[:, sl] @ self.keys[i, :position + 1, sl].T + ATT_OFF
                delta = raw.max(-1, keepdims=True) - raw
                exponent = self.exp_of_delta(delta)
                weights_int = exponent * 10000 // exponent.sum(-1, keepdims=True)
                attention[:, sl] = tdiv(weights_int @ self.values[i, :position + 1, sl], 10000)
            x = x + self.linear(attention, "proj", weights["proj"])
            normalized = self.layernorm(x, weights["ln2"])
            hidden = np.maximum(0, self.linear(normalized, "fc1", weights["fc1"]))
            x = x + self.linear(hidden, "fc2", weights["fc2"])
        self.position += 1
        return tdiv(self.layernorm(x, self.lnf) @ self.emb_q.T, 1000)[0]

    def complete(self, prompt, max_new=200):
        ids = encode_normalized(prompt).tolist()
        if not ids or len(ids) >= self.ctx:
            raise ValueError("Prompt must fit within the 256-character context.")
        self.reset()
        for token in ids:
            logits = self.step(token)
        for _ in range(min(max_new, self.ctx - len(ids))):
            token = int(np.argmax(logits))
            yield self.vocab[token]
            if token == NEWLINE:
                break
            logits = self.step(token)


def answer(model, history, question, max_new):
    question = normalize(question).replace("\n", " ").strip()
    if not question:
        raise ValueError("Введите вопрос по-английски: a-z и знаки препинания.")
    prefix = f"you: {question}\nbot: "
    if len(prefix) >= model.ctx:
        raise ValueError("Вопрос слишком длинный: вместе с разметкой он должен занимать меньше 256 символов.")
    if len(history + prefix) >= model.ctx:
        print("[Контекст заполнен — начинаю новый разговор.]", file=sys.stderr)
        history = ""
    prompt = history + prefix
    reply = ""
    print("bot: ", end="", flush=True)
    for char in model.complete(prompt, max_new):
        reply += char
        if char != "\n":
            print(char, end="", flush=True)
    print()
    if not reply.endswith("\n"):
        print("[Достигнут предел генерации или контекста.]", file=sys.stderr)
    return prompt + reply + ("" if reply.endswith("\n") else "\n")


def main():
    parser = argparse.ArgumentParser(description="Factorio language model: standalone Python chat.")
    parser.add_argument("--prompt", help="Ask one question in English and exit.")
    parser.add_argument("--max-new", type=int, default=200, help="Maximum generated characters (default: 200).")
    args = parser.parse_args()
    if args.max_new < 1:
        parser.error("--max-new must be positive")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    model = IncrementalModel()
    if model.vocab != CHARS:
        raise ValueError("Weights and tokenizer alphabets differ.")
    if args.prompt is not None:
        try:
            answer(model, "", args.prompt, args.max_new)
        except ValueError as error:
            parser.error(str(error))
        return
    print("Вопросы — по-английски. /reset — очистить память, /quit — выйти.")
    history = ""
    while True:
        try:
            question = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if question == "/quit":
            return
        if question == "/reset":
            history = ""
            print("[Память очищена.]")
            continue
        if not question:
            continue
        try:
            history = answer(model, history, question, args.max_new)
        except ValueError as error:
            print(str(error), file=sys.stderr)


if __name__ == "__main__":
    main()
