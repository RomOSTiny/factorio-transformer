import random

CYRILLIC_MAP = {
    "а": ["a"], "б": ["b"], "в": ["v"], "г": ["g"], "д": ["d"],
    "е": ["e", "ye"], "ё": ["yo", "e"], "ж": ["zh", "j"], "з": ["z"],
    "и": ["i"], "й": ["y", "i", "j"], "к": ["k"], "л": ["l"], "м": ["m"],
    "н": ["n"], "о": ["o"], "п": ["p"], "р": ["r"], "с": ["s"], "т": ["t"],
    "у": ["u"], "ф": ["f"], "х": ["h", "kh", "x"], "ц": ["c", "ts"],
    "ч": ["ch"], "ш": ["sh"], "щ": ["sch", "shch", "w"], "ъ": [""],
    "ы": ["y", "i"], "ь": [""], "э": ["e"], "ю": ["yu", "iu", "u"],
    "я": ["ya", "ia", "a"],
}


def transliterate_once(text: str, rng: random.Random) -> str:
    out = []
    for ch in text.lower():
        options = CYRILLIC_MAP.get(ch)
        out.append(rng.choice(options) if options is not None else ch)
    return "".join(out)


def generate_variants(text: str, n: int, seed: int = 0):
    """Generate up to n distinct plausible latin transliterations of a russian phrase."""
    rng = random.Random(seed)
    variants = []
    seen = set()
    attempts = 0
    max_attempts = n * 20 + 50
    while len(variants) < n and attempts < max_attempts:
        v = transliterate_once(text, rng)
        attempts += 1
        if v not in seen:
            seen.add(v)
            variants.append(v)
    return variants
