import io
import contextlib
import json
import sys

g = {"__name__": "__not_main__"}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(compile(open("export_full.py").read(), "export_full.py", "exec"), g)

bp = g["bp"]
dump_path = r"C:\Users\natas\AppData\Roaming\Factorio\script-output\factorio_ai_debug.json"
with open(dump_path, encoding="utf-8") as f:
    dump = json.load(f)

TYPE_OFFSET = {
    "constant-combinator": (0.5, 0.5),
    "arithmetic-combinator": (0.5, 1.0),
    "decider-combinator": (0.5, 1.0),
}


def tile_xy(e):
    p = e.tile_position
    return (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])


def build_lookup(pure_offset):
    id_to_real = {}
    for e in bp.entities:
        if e.name not in TYPE_OFFSET:
            continue
        tx, ty = tile_xy(e)
        tox, toy = TYPE_OFFSET[e.name]
        rx = round(tx + tox + pure_offset[0], 1)
        ry = round(ty + toy + pure_offset[1], 1)
        id_to_real[e.id] = (rx, ry, e.name)
    return id_to_real


by_pos = {}
for r in dump:
    by_pos.setdefault((round(r["x"], 1), round(r["y"], 1)), []).append(r)


def get_signal_dict(id_to_real, eid, side="output"):
    rx, ry, name = id_to_real[eid]
    out = {}
    for r in by_pos.get((rx, ry), []):
        if r["type"] != name:
            continue
        for s in r.get(side, []) or []:
            out[s["name"]] = s["count"]
    return out


WINNER_SIGNALS = g["WINNER_SIGNALS"]
CLASSES = g["CLASSES"]
winner_idx = g["winner_idx"]
hidden = g["hidden"]
HIDDEN_SIGNALS = g["HIDDEN_SIGNALS"]


def check(pure_offset, label):
    print(f"\n===== offset {label} = {pure_offset} =====")
    id_to_real = build_lookup(pure_offset)
    rc = get_signal_dict(id_to_real, "relay_1_0")
    print("relay_1_0 (expect iron-chest=20062):", rc)
    hp = get_signal_dict(id_to_real, "hidden_pool")
    mism = 0
    for j, name in enumerate(HIDDEN_SIGNALS):
        expected = int(round(hidden[j] * 1000))
        actual = hp.get(name, "MISSING")
        if actual != expected:
            mism += 1
    print(f"hidden_pool mismatches: {mism}/{len(HIDDEN_SIGNALS)}")
    winner_set = set(WINNER_SIGNALS)
    hits = {}
    for eid, (rx, ry, name) in id_to_real.items():
        if name != "decider-combinator" or "argmax" not in eid:
            continue
        sd = get_signal_dict(id_to_real, eid)
        for sig, count in sd.items():
            if sig in winner_set:
                hits.setdefault(sig, 0)
                hits[sig] += 1
    print(f"Expected winner signal: {WINNER_SIGNALS[winner_idx]} (class {winner_idx}='{CLASSES[winner_idx]}')")
    for sig, cnt in hits.items():
        idx = WINNER_SIGNALS.index(sig)
        print(f"  FIRED: {sig} (class {idx}='{CLASSES[idx]}') x{cnt} entities")
    if not hits:
        print("  NOTHING FIRED")


offsets = [(-46.0, -204.0, "landmark2 (-45.5)"), (-275.0, -210.0, "landmark1 (-274.5)")]
for ox, oy, label in offsets:
    check((ox, oy), label)
