"""Canonical signal keys for signals of every Factorio 2.0 type (and quality).

A key is the plain name when the signal has its name's default type (draftsman's first type for that
name: item before recipe/entity, virtual for signal-*) and normal quality - so every existing block
(virtual / item signals only) keeps its keys unchanged - otherwise "name|type|quality".
Used by circuit_builder (blueprint JSON), circuit_sim (network values) and the live readers.
"""
from draftsman.data import signals as SD
from draftsman.signatures import SignalID

QUALITIES = ("normal", "uncommon", "rare", "epic", "legendary")
TYPES = ("virtual", "item", "fluid", "entity", "recipe", "space-location", "asteroid-chunk", "quality")
_TYPE_LISTS = {"virtual": SD.virtual, "item": SD.item, "fluid": SD.fluid, "entity": SD.entity, "recipe": SD.recipe,
               "space-location": SD.space_location, "asteroid-chunk": SD.asteroid_chunk, "quality": SD.quality}
# never usable as data: wildcards, blueprint parameters, quality-unknown
RESERVED = {"signal-everything", "signal-each", "signal-anything", "signal-unknown", "quality-unknown"}


def default_type(name):
    t = SD.type_of.get(name)
    return t[0] if t else "item"


def key(name, type=None, quality=None):
    type = type or default_type(name)
    quality = quality or "normal"
    if type == default_type(name) and quality == "normal":
        return name
    return f"{name}|{type}|{quality}"


def split(k):
    """key -> (name, type, quality)"""
    if "|" in k:
        n, t, q = k.split("|")
        return n, t, q
    return k, default_type(k), "normal"


def from_json(s):
    """Blueprint signal dict {name, type?, quality?} -> key (None for empty)."""
    if not s or not s.get("name"):
        return None
    return key(s["name"], s.get("type") or "item", s.get("quality"))


def sid(k):
    """key -> what draftsman accepts as a signal (plain name keeps draftsman's own defaults)."""
    if k is None or "|" not in k:
        return k
    n, t, q = split(k)
    return SignalID(name=n, type=t, quality=q)


def pool(n, exclude=(), types=TYPES, qualities=("normal",)):
    """n distinct signal keys, virtual first, then items, fluids, entities, recipes, ...;
    each type's list in draftsman order. Verified live (final_prims_test): all 2171 normal-quality keys
    of every type pass a circuit network (hidden entities too); the 5 qualities are distinct signals;
    only the blueprint-parameter signals (*parameter*) are dropped by the game."""
    exclude = set(exclude)
    out = []
    for q in qualities:
        for t in types:
            for name in _TYPE_LISTS[t]:
                if name in RESERVED or "parameter" in name:        # blueprint parameters: dropped live
                    continue
                k = key(name, t, q)
                if k in exclude or k in out:
                    continue
                out.append(k)
                if len(out) == n:
                    return out
    raise ValueError(f"signal pool exhausted: {len(out)} < {n}")
