import io
import contextlib
import json

g = {"__name__": "__not_main__"}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(compile(open("export_full.py").read(), "export_full.py", "exec"), g)

bp = g["bp"]
dump = json.load(open(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\factorio_ai_debug.json", encoding="utf-8"))

TYPE_OFFSET = {
    "constant-combinator": (0.5, 0.5),
    "arithmetic-combinator": (0.5, 1.0),
    "decider-combinator": (0.5, 1.0),
}


def tile_xy(e):
    p = e.tile_position
    return (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])


pure_offset = (-275.0, -210.0)
id_to_real = {}
for e in bp.entities:
    if e.name not in TYPE_OFFSET:
        continue
    tx, ty = tile_xy(e)
    tox, toy = TYPE_OFFSET[e.name]
    id_to_real[e.id] = (round(tx + tox + pure_offset[0], 1), round(ty + toy + pure_offset[1], 1), e.name)

by_pos = {}
for r in dump:
    by_pos.setdefault((round(r["x"], 1), round(r["y"], 1)), []).append(r)


def sig(eid, side="output"):
    rx, ry, name = id_to_real[eid]
    out = {}
    for r in by_pos.get((rx, ry), []):
        if r["type"] != name:
            continue
        for s in r.get(side, []) or []:
            out[s["name"]] = s["count"]
    return out


OUTPUT_SIGNALS = g["OUTPUT_SIGNALS"]
logits = g["logits"]
ALL_OUTPUTS = g["ALL_OUTPUTS"]
CLASSES = g["CLASSES"]

print("ALL_OUTPUTS id:", ALL_OUTPUTS)
d = sig(ALL_OUTPUTS)
print(f"signals found: {len(d)} / 50 expected\n")
mism = 0
for k, name in enumerate(OUTPUT_SIGNALS):
    expected = int(round(logits[k] * 1000))
    actual = d.get(name, "MISSING")
    ok = actual == expected
    if not ok:
        mism += 1
    print(f"  class {k:2d} {CLASSES[k]:25s} {name:35s} expected={expected:7d} actual={actual!s:>10s} {'OK' if ok else 'X'}")
print(f"\nmismatches: {mism}/50")

winner_idx = g["winner_idx"]
ranked_actual = sorted(range(50), key=lambda k: -(d.get(OUTPUT_SIGNALS[k], -999999)))
print(f"\npython winner: {winner_idx} ({CLASSES[winner_idx]})")
print(f"actual top5 by dumped value: {[(k, CLASSES[k], d.get(OUTPUT_SIGNALS[k])) for k in ranked_actual[:5]]}")
