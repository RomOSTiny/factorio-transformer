"""Generate Factorio / persona chat dialogues from knowledge/*.txt into the "factorio" source.

    python generate_factorio.py [n_train_dialogues]
    python generate_factorio.py --show 5          # print samples, write nothing
"""
import random
import re
import sys
from pathlib import Path

from prepare_data import MAX_TURN_CHARS, Writer
from tokenizer import BOT, USER, normalize

KNOW = Path(__file__).parent / "knowledge"
STORY_MAX = 200
SINGULAR_S = {"nauvis", "vulcanus"}


def parse(path):
    topics = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            topics.append({"names": [n.strip() for n in line[3:].split("|")], "q": [], "facts": [], "op": []})
        elif not line or line.startswith("#"):
            continue
        else:
            kind, text = line[0], normalize(line[1:].replace("(?)", ""))
            topics[-1][{"?": "q", "-": "facts", "+": "op"}[kind]].append(text)
    return topics


FACTS = [t for p in sorted(KNOW.glob("factorio*.txt")) for t in parse(p) if t["facts"]]
PERSONA, PERSONA_W = {}, {}
for _p in sorted(KNOW.glob("persona*.txt")):
    # identity is shown more often than the rest: it must be remembered word for word
    _w = 3 if "creator" in _p.name else 2 if "reactions" in _p.name else 1
    for _t in parse(_p):
        PERSONA[_t["names"][0]], PERSONA_W[_t["names"][0]] = _t, _w
STORIES = [t for p in sorted(KNOW.glob("stories*.txt")) for t in parse(p) if t["facts"]]
PLANETS = ["nauvis", "vulcanus", "fulgora", "gleba", "aquilo"]

ABOUT = ["tell me about {x}.", "what do you know about {x}?", "can you tell me about {x}?", "i want to know about {x}.",
         "explain {x} to me.", "tell me something about {x}.", "do you know anything about {x}?", "{x}?",
         "what can you tell me about {x}?", "i have a question about {x}.", "what does {x} do?",
         "how do i make {x}?", "how do i get {x}?", "how do {x} work?", "why do i need {x}?", "where do i find {x}?",
         "what is {x} for?", "how do i use {x}?", "i don't understand {x}.", "teach me about {x}."]
MORE = ["tell me more.", "what else?", "and?", "tell me more about it!", "cool! what else?", "interesting. anything else?",
        "go on!", "more please!", "what else do you know?"]
RELATED = ["and what about {y}?", "what about {y}?", "ok. and {y}?", "tell me about {y} too.", "and {y}?"]
LIKE_Q = ["do you like {x}?", "what do you think about {x}?", "how do you feel about {x}?", "are {x} good?"]
REACT_U = ["wow!", "cool!", "nice!", "i did not know that.", "that is interesting!", "awesome!", "haha", "ok", "oh, i see."]
REACT_B = ["yes! factorio is full of surprises.", "right? i love this stuff.", "do you want to know more?",
           "there is so much more to learn!", "i know, it is amazing.", "ask me anything else!"]
OPENERS = ["", "", "", "", "", "good question! ", "oh, i know this! ", "sure! ", "let me tell you. ", "well, ", "ah, {x}! "]
STORY_Q = ["tell me a story about {x}.", "can you tell me a story about {x}?", "do you have a story about {x}?",
           "i want a story about {x}!", "tell me about a time with {x}."]
STORY_ANY = ["tell me a story.", "tell me a factorio story.", "do you have a story?", "tell me about your adventures.",
             "what happened to you today?"]
NO_MORE = ["that is all i know about {x}.", "hmm, i think that is everything about {x}.", "i do not know more about {x}."]
NAMES = ("roma roman ivan sasha dima anya katya lena misha nikita maxim artem vlad igor oleg yura kolya petya "
         "lily tom ben mia sam anna max kate john emma jack alex leo nina sara mike tim lucy sofia daniel").split()
TELL_NAME = ["my name is {n}.", "i am {n}.", "my name {n}", "call me {n}.", "i'm {n}!", "hi, i am {n}.",
             "{n} is my name.", "you can call me {n}.", "hello, my name is {n}!", "im {n}"]
GREET_NAME = ["nice to meet you, {n}!", "hello, {n}! welcome to my factory.", "hi, {n}! that is a good name.",
              "nice to meet you, {n}. i am the engineer.", "hello there, {n}!", "{n}! good to meet you."]
ASK_NAME = ["what is my name?", "whats my name", "do you remember my name?", "do you know my name?",
            "say my name", "my name?", "what did i say my name was?"]
SAY_NAME = ["your name is {n}.", "you are {n}!", "{n}, of course.", "you told me, you are {n}.",
            "your name is {n}, i remember!", "{n}. i wrote it on a belt."]
NO_NAME = ["you have not told me your name yet. what is it?", "i do not know it yet! tell me your name.",
           "you did not tell me. what should i call you?"]


def typo(rng, text):
    """One small slip, the kind you make typing fast - so the bot still understands a misspelt question."""
    i = rng.randrange(len(text))
    if text[i] == " " or not text[i].isalpha():
        return text
    kind = rng.random()
    if kind < 0.4:
        return text[:i] + text[i + 1:]                      # dropped letter
    if kind < 0.7 and i + 1 < len(text) and text[i + 1].isalpha():
        return text[:i] + text[i + 1] + text[i] + text[i + 2:]   # swapped letters
    return text[:i] + text[i] + text[i:]                    # doubled letter


def user(rng, text):
    text = text.strip()
    if rng.random() < 0.25 and text[-1] in ".?!":
        text = text[:-1]
    if rng.random() < 0.08:
        text = rng.choice(["hey, ", "so, ", "engineer, ", "um, "]) + text
    if rng.random() < 0.06:
        text = typo(rng, text)
    if rng.random() < 0.05:
        text = text.replace("'", "")                        # "dont", "whats" - people skip apostrophes
    return USER + text


def facts_reply(rng, topic, used, opener=True):
    pool = [f for f in topic["facts"] if f not in used]
    if not pool:
        return None
    rng.shuffle(pool)
    x = topic["names"][0]
    out = rng.choice(OPENERS).format(x=x).strip() if opener else ""
    for f in pool[:rng.choice([1, 1, 2, 2, 3])]:
        if len(out) + len(f) + 1 > MAX_TURN_CHARS:
            break
        out = f"{out} {f}" if out else f
        used.add(f)
    return out if used & set(topic["facts"]) and out else None


# Some topic names are whole phrases ("how long is the game", "my factory is a mess"): they do not fit
# templates like "do you like {x}?", so those topics are asked about only with their own questions.
_PHRASE = re.compile(r"^(how|what|is|why|where|when|can|do|my|i|no|too|not|running|starting|slow|best|biters)\b|"
                     r"\bor\b|\bis\b")


def plain_names(topic):
    return [n for n in topic["names"] if not _PHRASE.search(n)]


def ask_topic(rng, topic):
    names = plain_names(topic)
    if topic["q"] and (rng.random() < 0.4 or not names):
        return rng.choice(topic["q"])
    if not names:
        return rng.choice(ABOUT).format(x=topic["names"][0])
    name = rng.choice(names)
    if rng.random() < 0.25:
        be = "are" if name.endswith("s") and name not in SINGULAR_S else "is"
        return f"what {be} {name}?"
    return rng.choice(ABOUT).format(x=name)


class Dialogue:
    def __init__(self, rng):
        self.rng, self.lines, self.topic, self.used = rng, [], None, set()

    def say(self, u, b):
        self.lines += [user(self.rng, u), BOT + b]

    def fact(self):
        self.topic = self.rng.choice(FACTS)
        self.used = set()
        self.say(ask_topic(self.rng, self.topic), facts_reply(self.rng, self.topic, self.used))

    def more(self):
        r = facts_reply(self.rng, self.topic, self.used, opener=False)
        self.say(self.rng.choice(MORE), r or self.rng.choice(NO_MORE).format(x=self.topic["names"][0]))

    def related(self):
        i = FACTS.index(self.topic)
        j = min(len(FACTS) - 1, max(0, i + self.rng.choice([-3, -2, -1, 1, 2, 3])))
        self.topic, self.used = FACTS[j], set()
        names = plain_names(self.topic)
        ask = self.rng.choice(RELATED).format(y=self.rng.choice(names)) if names else ask_topic(self.rng, self.topic)
        self.say(ask, facts_reply(self.rng, self.topic, self.used))

    def opinion(self):
        t = self.rng.choice([t for t in FACTS if t["op"] and plain_names(t)])
        x = self.rng.choice(plain_names(t))
        if self.rng.random() < 0.3:
            b = self.rng.choice(["me too! ", "really? ", "nice! "]) + self.rng.choice(t["op"])
            self.say(f"i like {x}!", b)
        else:
            b = self.rng.choice(t["op"])
            extra = self.rng.choice([f for f in t["facts"]])
            if self.rng.random() < 0.4 and len(b) + len(extra) < MAX_TURN_CHARS:
                b += " " + extra
            q = self.rng.choice(LIKE_Q)
            if q.startswith("are") and not (x.endswith("s") and x not in SINGULAR_S):
                q = "is {x} good?"
            self.say(q.format(x=x), b)
        self.topic, self.used = t, set()

    def persona(self, name=None):
        if name:
            t = PERSONA[name]
        else:
            keys = [k for k in PERSONA if k not in ("bye", "thanks")]
            t = PERSONA[self.rng.choices(keys, weights=[PERSONA_W[k] for k in keys])[0]]
        b = self.rng.choice(t["facts"])
        if self.rng.random() < 0.15:
            b2 = self.rng.choice(t["facts"])
            if b2 != b and len(b) + len(b2) < MAX_TURN_CHARS:
                b += " " + b2
        self.say(self.rng.choice(t["q"]), b)

    def story(self):
        t = self.rng.choice(STORIES)
        s = self.rng.choice([s for s in t["facts"] if len(s) <= STORY_MAX] or t["facts"])
        q = self.rng.choice(STORY_Q).format(x=self.rng.choice(t["names"])) if self.rng.random() < 0.7 \
            else self.rng.choice(STORY_ANY)
        self.say(q, self.rng.choice(["", "", "okay! ", "sure! ", "oh, i have one! "]) + s)

    def plays(self):
        self.say(self.rng.choice(["i play factorio too!", "i also play factorio.", "i love factorio!"]),
                 self.rng.choice(["that is great! what is your favorite planet?", "nice! which planet do you like?",
                                  "cool! what is your favorite planet?"]))
        p = self.rng.choice(PLANETS)
        t = next(t for t in FACTS if t["names"][0] == p)
        b = self.rng.choice([f"{p} is a good choice! ", f"oh, {p}! ", "nice! "])
        b += self.rng.choice(t["op"]) if t["op"] and self.rng.random() < 0.5 else self.rng.choice(t["facts"])
        self.say(self.rng.choice([f"{p}!", f"i like {p}.", f"{p}, i think.", f"probably {p}."]), b)

    def introduce(self):
        """Learn to take a name from the conversation and give it back - pure copying from context."""
        n = self.rng.choice(NAMES)
        if self.rng.random() < 0.2:      # asked before being told
            self.say(self.rng.choice(ASK_NAME), self.rng.choice(NO_NAME))
        self.say(self.rng.choice(TELL_NAME).format(n=n), self.rng.choice(GREET_NAME).format(n=n))
        if self.rng.random() < 0.7:
            self.say(self.rng.choice(ASK_NAME), self.rng.choice(SAY_NAME).format(n=n))

    def react(self):
        b = self.rng.choice(self.topic["op"]) if self.topic and self.topic["op"] and self.rng.random() < 0.5 \
            else self.rng.choice(REACT_B)
        self.say(self.rng.choice(REACT_U), b)


def dialogue(rng):
    d = Dialogue(rng)
    if rng.random() < 0.3:
        d.persona("greeting")
    if rng.random() < 0.12:      # the user introduces themselves early, as people do
        d.introduce()
    for k in range(rng.choice([1, 1, 2, 2, 3, 3, 4])):
        r = rng.random()
        if d.topic and r < 0.25:
            d.more() if rng.random() < 0.6 else d.related()
        elif r < 0.55:
            d.fact()
        elif r < 0.77:          # persona gets a big share: general chat data pulls the bot's identity apart
            d.persona()
        elif r < 0.85:
            d.opinion()
        elif r < 0.92:
            d.story()
        elif r < 0.96:
            d.plays()
        elif d.topic:
            d.react()
        else:
            d.fact()
    if rng.random() < 0.25:
        d.persona(rng.choice(["thanks", "bye"]))
    return "\n".join(d.lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:2] == ["--show"]:
        rng = random.Random()
        for _ in range(int(sys.argv[2])):
            print(dialogue(rng), end="\n\n")
        return
    n_train = int(sys.argv[1]) if len(sys.argv) > 1 else 300_000
    print(f"topics: {len(FACTS)} fact, {len(PERSONA)} persona, {len(STORIES)} story; "
          f"facts {sum(len(t['facts']) for t in FACTS)}")
    for split, n in (("val", 3000), ("train", n_train)):
        rng = random.Random(f"factorio-{split}")
        w = Writer("factorio", split)
        for _ in range(n):
            w.add(dialogue(rng))
        w.close()


if __name__ == "__main__":
    main()
