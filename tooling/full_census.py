import io
import contextlib
import json

PURE_OFFSET = (-61.0, -135.0)

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


expected = {}  # (rx,ry,type) -> id
for e in bp.entities:
    if e.name not in TYPE_OFFSET:
        continue
    tx, ty = tile_xy(e)
    tox, toy = TYPE_OFFSET[e.name]
    rx = round(tx + tox + PURE_OFFSET[0], 1)
    ry = round(ty + toy + PURE_OFFSET[1], 1)
    expected[(rx, ry, e.name)] = e.id

actual = set()
for r in dump:
    actual.add((round(r["x"], 1), round(r["y"], 1), r["type"]))

expected_keys = set(expected.keys())
missing = expected_keys - actual
extra = actual - expected_keys

print(f"expected: {len(expected_keys)}, actual in dump: {len(actual)}")
print(f"missing (in blueprint, not in game): {len(missing)}")
print(f"extra (in game, not in blueprint - shouldn't happen): {len(extra)}")
print()
print("Missing entities (blueprint id, position, type):")
for rx, ry, t in sorted(missing, key=lambda k: (k[2], k[0], k[1])):
    print(f"  {expected[(rx,ry,t)]:20s} {t:22s} ({rx}, {ry})")
if extra:
    print("\nExtra (unexpected) entities:")
    for rx, ry, t in sorted(extra):
        print(f"  {t:22s} ({rx}, {ry})")
