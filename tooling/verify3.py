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


pure_offset = (-61.0, -135.0)
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
winner_idx = g["winner_idx"]
HIDDEN_SIGNALS = g["HIDDEN_SIGNALS"]
hidden = g["hidden"]

print("=== relay_1_0 (window code, expect iron-chest=20062) ===")
print(sig("relay_1_0"))

print("\n=== hidden_pool ===")
hp = sig("hidden_pool")
mism = sum(1 for j, name in enumerate(HIDDEN_SIGNALS) if hp.get(name) != int(round(hidden[j] * 1000)))
print(f"mismatches: {mism}/{len(HIDDEN_SIGNALS)}  (found {len(hp)} signals)")

print("\n=== ALL_OUTPUTS ===", ALL_OUTPUTS)
d = sig(ALL_OUTPUTS)
print(f"signals found: {len(d)}/50")
mism2 = 0
for k, name in enumerate(OUTPUT_SIGNALS):
    expected = int(round(logits[k] * 1000))
    actual = d.get(name, "MISSING")
    ok = actual == expected
    if not ok:
        mism2 += 1
print(f"mismatches: {mism2}/50")
if mism2:
    for k, name in enumerate(OUTPUT_SIGNALS):
        expected = int(round(logits[k] * 1000))
        actual = d.get(name, "MISSING")
        if actual != expected:
            print(f"  class {k} {CLASSES[k]}: expected={expected} actual={actual}")

print(f"\npython winner: {winner_idx} ({CLASSES[winner_idx]})")

print("\n=== argmax fired signals ===")
WINNER_SIGNALS = g["WINNER_SIGNALS"]
winner_set = set(WINNER_SIGNALS)
hits = {}
for eid, (rx, ry, name) in id_to_real.items():
    if name != "decider-combinator" or "argmax" not in eid:
        continue
    sd = sig(eid)
    for s, c in sd.items():
        if s in winner_set:
            hits.setdefault(s, 0)
            hits[s] += 1
for s, cnt in hits.items():
    idx = WINNER_SIGNALS.index(s)
    print(f"  FIRED: {s} class {idx} ({CLASSES[idx]}) x{cnt}")
if not hits:
    print("  nothing fired")
