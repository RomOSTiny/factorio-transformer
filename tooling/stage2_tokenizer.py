"""
Stage 2 tokenizer: character-level, matching the project's original plan
("generative version - English, no translit, simple tokenization" -
PROJECT.md intro) and the vocab~50 assumption used in the Reshenie 13/17
entity budget. Same letter-code spirit as the classifier's CHEAT_SHEET.md
(a=1..z=26, space=27) - lowercase-normalized, small fixed alphabet, easy
to build a ROM-addressed embedding table for.

Vocab chosen by looking at real TinyStories text (see
stage2_data_prep.py): lowercase letters + space + the punctuation that
actually shows up in simple children's stories (. , ! ? ' " -) + newline
as a story/paragraph separator. Digits and rarer punctuation are dropped
(mapped to nothing) rather than given their own slot - keeps the vocab
small and the embedding table cheap, at the cost of occasionally losing a
rare character. Tiny model, tiny vocab, honest tradeoff.
"""

CHARS = list("abcdefghijklmnopqrstuvwxyz .,!?'\"-\n")
STOI = {c: i for i, c in enumerate(CHARS)}
ITOS = {i: c for i, c in enumerate(CHARS)}
VOCAB_SIZE = len(CHARS)


def encode(text):
    text = text.lower()
    out = []
    for ch in text:
        i = STOI.get(ch)
        if i is not None:
            out.append(i)
    return out


def decode(ids):
    return "".join(ITOS[i] for i in ids)


if __name__ == "__main__":
    print(f"Vocab size: {VOCAB_SIZE}")
    print(f"Chars: {CHARS}")
    sample = "One day, a little girl named Lily found a needle!"
    enc = encode(sample)
    print(f"Sample: {sample!r}")
    print(f"Encoded: {enc}")
    print(f"Decoded: {decode(enc)!r}")
