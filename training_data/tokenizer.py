"""Character tokenizer: the 35-symbol alphabet from the spec + ':' (index 35) for dialogue role markers.

Chat format (one line per turn, a blank line between documents):
    you: hi! who are you?
    bot: i am an engineer. i build a factory.
':' never appears in normal text - normalize() drops it - so it only marks the roles.
"""
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
