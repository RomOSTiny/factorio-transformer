"""Build the training corpus.

For every source and split writes to DATA_DIR:
    <name>_<split>.bin        uint8 token ids; documents separated by a blank line ("\n\n")
    <name>_<split>_docs.npy   int64 offsets of document starts
    <name>_<split>_turns.npy  int64 offsets of user-turn starts ("you: ..."), dialogue sources only

Sources:
    tinystories   stories, paragraphs separated by "\n"
    storychat     "you: tell me a story ..." -> "bot: <first paragraph of a TinyStories story>"
    tinydialogues two-speaker child-directed conversations (GPT-4, MIT)
    soda          two-speaker everyday conversations (CC BY 4.0)
    personachat   getting-to-know-you small talk (CC BY 4.0)

Usage: python prepare_data.py [source ...]   (default: all)
"""
import random
import re
import sys
import time
from pathlib import Path

import numpy as np

from tokenizer import BOT, TYPO_MAP, USER, encode_normalized, normalize

RAW = Path(__file__).resolve().parent / "raw"
DATA_DIR = Path(__file__).resolve().parent / "corpus"

MAX_TURN_CHARS = 160   # context is 256: a longer turn ends the dialogue there
SEED = 1234

_DIGIT = re.compile(r"\d")
_ACTION = re.compile(r"\*[^*]*\*|\([^)]*\)|\[[^\]]*\]")
# characters that normalize() drops silently without harming the text
_HARMLESS_DROPS = re.compile(r"[a-z .,!?'\"\-\n:;()\u0300-\u036f]")


class Writer:
    """Streams documents into <name>_<split>.bin, remembering document and user-turn offsets."""

    def __init__(self, name, split):
        self.path = DATA_DIR / f"{name}_{split}"
        self.f = open(f"{self.path}.bin", "wb")
        self.pos, self.docs, self.turns, self.buf = 0, [], [], []

    def add(self, doc: str):
        self.buf.append(doc)
        if len(self.buf) >= 20000:
            self.flush()

    def flush(self):
        if not self.buf:
            return
        chunk = "".join(d + "\n\n" for d in self.buf)
        base = self.pos
        for d in self.buf:
            self.docs.append(base)
            if d.startswith(USER):
                self.turns.append(base)
            for m in re.finditer("\n" + USER, d):
                self.turns.append(base + m.start() + 1)
            base += len(d) + 2
        self.f.write(encode_normalized(chunk).tobytes())
        self.pos = base
        self.buf = []

    def close(self):
        self.flush()
        self.f.close()
        np.save(f"{self.path}_docs.npy", np.array(self.docs, dtype=np.int64))
        if self.turns:
            np.save(f"{self.path}_turns.npy", np.array(self.turns, dtype=np.int64))
        print(f"  {self.path.name}: {len(self.docs):,} docs, {self.pos:,} chars, {len(self.turns):,} user turns")


# ---------------------------------------------------------------- stories

def clean_story(raw: str):
    if _DIGIT.search(raw):
        return None
    probe = raw.replace("\u2026", "...").translate(TYPO_MAP).lower()
    if len(_HARMLESS_DROPS.sub("", probe)) > 2:   # foreign text, symbols, emoji ...
        return None
    paragraphs = [normalize(p) for p in raw.split("\n")]
    text = "\n".join(p for p in paragraphs if p)
    return text if len(text) >= 100 else None


def iter_tinystories(split):
    fname = {"train": "TinyStoriesV2-GPT4-train.txt", "val": "TinyStoriesV2-GPT4-valid.txt"}[split]
    lines = []
    with open(RAW / fname, encoding="utf-8") as f:
        for line in f:
            if "<|endoftext|>" in line:
                story = clean_story("".join(lines))
                lines = []
                if story:
                    yield story
            else:
                lines.append(line)


# ---------------------------------------------------------------- "tell me a story"

STORY_NOUNS = ("dog cat bird fish bunny rabbit bear lion frog duck mouse horse cow pig sheep monkey elephant "
               "dragon princess prince king queen fairy monster robot unicorn owl fox squirrel butterfly bee "
               "ball kite car train boat plane truck toy doll balloon cake cookie tree flower garden park "
               "beach sea river forest castle house star moon sun rain snow").split()
REQUESTS_ABOUT = ["tell me a story about a {x}.", "can you tell me a story about a {x}?", "i want a story about a {x}!",
                  "do you know a story about a {x}?", "please tell me a story about a {x}.",
                  "tell me a story with a {x} in it.", "a story about a {x}, please!"]
REQUESTS_ANY = ["tell me a story.", "can you tell me a story?", "tell me a story, please!", "i want to hear a story.",
                "do you know any stories?", "tell me a bedtime story.", "tell me a short story.", "story time!"]
LEAD_INS = ["", "", "", "okay! ", "sure! ", "of course! ", "okay, here is a story. ", "i know one! "]


def first_paragraph(story: str, limit=200):
    para = story.split("\n")[0]
    cut = para[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if len(para) <= limit:
        return para
    return cut[:end + 1] if end >= 40 else None


def iter_storychat(split, rng):
    for story in iter_tinystories(split):
        if rng.random() > 0.15:          # a small derived set is enough
            continue
        para = first_paragraph(story)
        if not para:
            continue
        words = set(re.findall(r"[a-z]+", para))
        found = [n for n in STORY_NOUNS if n in words]
        ask = rng.choice(REQUESTS_ABOUT).format(x=rng.choice(found)) if found and rng.random() < 0.7 \
            else rng.choice(REQUESTS_ANY)
        yield f"{USER}{ask}\n{BOT}{rng.choice(LEAD_INS)}{para}"


# ---------------------------------------------------------------- dialogues

def clean_turn(text: str) -> str:
    text = _ACTION.sub(" ", text).strip()
    if len(text) >= 2 and text[0] in "\"\u201c" and text[-1] in "\"\u201d":
        text = text[1:-1]
    return normalize(text.replace("\n", " "))


def strip_vocatives(text: str, names) -> str:
    """Drop the other person's name used as address ("oh, jibril, i'm sorry" -> "oh, i'm sorry")."""
    for name in names:
        n = re.escape(name)
        text = re.sub(rf"^{n}[,!.?]\s*", "", text)
        text = re.sub(rf",\s*{n}(?=[.,!?]|$)", "", text)
        text = re.sub(rf"\b(hi|hey|hello|oh|thanks|thank you|bye|goodbye|yes|no|okay|well|sorry|wow) {n}\b", r"\1", text)
    return text.strip()


def format_dialogue(turns, names=(), user_speakers=None):
    """turns: [(speaker, raw text)] -> "you: ...\\nbot: ..." or None.

    Roles: user_speakers if given (the rest become the bot, so three-party conversations work too),
    otherwise the speaker with longer turns on average becomes the bot - that teaches substantive answers.
    The dialogue is cut before the first turn that is too long, has digits or ends up empty."""
    names = [normalize(n) for n in names if n and len(n) > 1]
    merged = []
    for spk, raw in turns:
        if _DIGIT.search(raw):
            break
        text = strip_vocatives(clean_turn(raw), names)
        if not text:
            break
        if merged and merged[-1][0] == spk:
            merged[-1][1] += " " + text
        else:
            merged.append([spk, text])
    speakers = {s for s, _ in merged}
    if user_speakers is None:
        if len(speakers) != 2:
            return None
        mean = {s: np.mean([len(t) for x, t in merged if x == s]) for s in speakers}
        user_speakers = {min(speakers, key=mean.get)}
    elif not (speakers - user_speakers) or not (speakers & user_speakers):
        return None

    roles = []   # map speakers onto two roles, then merge again: two adults in a row are one bot turn
    for spk, text in merged:
        role = USER if spk in user_speakers else BOT
        if roles and roles[-1][0] == role:
            roles[-1][1] += " " + text
        else:
            roles.append([role, text])
    cut = next((i for i, (_, t) in enumerate(roles) if len(t) > MAX_TURN_CHARS), len(roles))
    roles = roles[:cut]
    if len(roles) < 2 or len({r for r, _ in roles}) != 2:
        return None
    return "\n".join(role + text for role, text in roles)


_TD_TURN = re.compile(r"^\*\*(.+?)\*\*\s*(\([^)]*\))?\s*:\s*(.*)$", re.S)


def iter_tinydialogues(split):
    fname = {"train": "tinydialogue_train_ordered.txt", "val": "tinydialogue_val_ordered.txt"}[split]
    text = (RAW / "TinyDialogues" / fname).read_text(encoding="utf-8")
    for conv in text.split("<|endoftext|>"):
        turns = []
        for part in conv.split("\\n\\n"):
            m = _TD_TURN.match(part.strip())
            if m:
                turns.append((m.group(1).strip(), m.group(3)))
        speakers = {s for s, _ in turns}
        # the child asks, the grown-ups explain - the same roles our bot plays. That also keeps
        # three-party conversations (about half of the dataset) instead of dropping them.
        doc = format_dialogue(turns, user_speakers={"Child"} if "Child" in speakers else None)
        if doc:
            yield doc


def iter_soda(split):
    import pyarrow.parquet as pq
    fname = {"train": "train.parquet", "val": "valid.parquet"}[split]
    table = pq.ParquetFile(RAW / "soda" / fname)
    for batch in table.iter_batches(batch_size=20000, columns=["dialogue", "speakers", "PersonX", "PersonY", "PersonZ"]):
        for row in batch.to_pylist():
            if len(set(row["speakers"])) != 2:
                continue
            names = {row["PersonX"], row["PersonY"], row["PersonZ"], *row["speakers"]}
            doc = format_dialogue(list(zip(row["speakers"], row["dialogue"])), names)
            if doc:
                yield doc


def iter_personachat(split):
    import pandas as pd
    fname = {"train": "Synthetic-Persona-Chat_train.csv", "val": "Synthetic-Persona-Chat_valid.csv"}[split]
    df = pd.read_csv(RAW / "Synthetic-Persona-Chat" / "data" / fname)
    for conv in df["Best Generated Conversation"].dropna():
        turns = []
        for line in conv.split("\n"):
            m = re.match(r"^\s*(User \d)\s*:\s*(.*)$", line)
            if m:
                turns.append((m.group(1), m.group(2)))
            elif turns and line.strip():
                turns[-1] = (turns[-1][0], turns[-1][1] + " " + line.strip())
        doc = format_dialogue(turns)
        if doc:
            yield doc


SOURCES = {
    "tinystories": lambda split, rng: iter_tinystories(split),
    "storychat": iter_storychat,
    "tinydialogues": lambda split, rng: iter_tinydialogues(split),
    "soda": lambda split, rng: iter_soda(split),
    "personachat": lambda split, rng: iter_personachat(split),
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    names = sys.argv[1:] or list(SOURCES)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in names:
        for split in ("val", "train"):
            t0 = time.time()
            rng = random.Random(f"{SEED}-{name}-{split}")
            w = Writer(name, split)
            for doc in SOURCES[name](split, rng):
                w.add(doc)
            w.close()
            print(f"    ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
