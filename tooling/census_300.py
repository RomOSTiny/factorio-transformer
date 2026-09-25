"""
Census for the full 300-syllable build: compares the entity list decoded
directly from the already-generated blueprint string (export_full_300syl.txt)
against the in-game dump (factorio_ai_debug.json, from
dump_signals_full_command.txt) to find what revive() failed to create.

Decodes the blueprint string directly (base64 -> zlib -> JSON) instead of
re-running export_full.py - the full 300-syllable generation takes ~25-30
minutes, and every position/type/control_behavior we need is already sitting
in the blueprint string's own JSON, so there's no reason to regenerate it.

The placement offset (where the player pasted the blueprint on the map) is
NOT hardcoded (unlike the previous session's PURE_OFFSET, which was specific
to that session's placement) - it's auto-detected by aligning the expected
and actual bounding boxes, since the blueprint is placed as a rigid
translation (no rotation/mirroring assumed - sanity-checked via width/height
match below).
"""

import base64
import json
import zlib

BP_FILE = "export_full_300syl.txt"
DUMP_FILE = r"C:\Users\natas\AppData\Roaming\Factorio\script-output\factorio_ai_debug.json"

CENSUS_TYPES = {"constant-combinator", "arithmetic-combinator", "decider-combinator"}

with open(BP_FILE, "r") as f:
    s = f.read()
raw = base64.b64decode(s[1:])
bp = json.loads(zlib.decompress(raw))["blueprint"]

expected_entities = [e for e in bp["entities"] if e["name"] in CENSUS_TYPES]
print(f"Expected (from blueprint string): {len(expected_entities)}")

dump = json.load(open(DUMP_FILE, encoding="utf-8"))
actual = [r for r in dump if r["type"] in CENSUS_TYPES]
print(f"Actual (in-game dump): {len(actual)}")

# ---- auto-detect placement offset via bounding-box alignment ----
ex_xs = [e["position"]["x"] for e in expected_entities]
ex_ys = [e["position"]["y"] for e in expected_entities]
ac_xs = [r["x"] for r in actual]
ac_ys = [r["y"] for r in actual]

ex_w, ex_h = max(ex_xs) - min(ex_xs), max(ex_ys) - min(ex_ys)
ac_w, ac_h = max(ac_xs) - min(ac_xs), max(ac_ys) - min(ac_ys)
print(f"Expected bbox: {ex_w:.1f} x {ex_h:.1f}")
print(f"Actual bbox:   {ac_w:.1f} x {ac_h:.1f}")
if abs(ex_w - ac_w) > 2 or abs(ex_h - ac_h) > 2:
    print("WARNING: bounding box size mismatch beyond 2 tiles - blueprint may be rotated/mirrored, or the surface has unrelated combinators mixed in. Offset below is unreliable, stop and investigate before trusting the missing/extra lists.")

offset_x = min(ac_xs) - min(ex_xs)
offset_y = min(ac_ys) - min(ex_ys)
print(f"Detected placement offset: ({offset_x:.2f}, {offset_y:.2f})")

# ---- match by (rounded position, type) ----
expected_keys = {}
for e in expected_entities:
    rx = round(e["position"]["x"] + offset_x, 1)
    ry = round(e["position"]["y"] + offset_y, 1)
    expected_keys[(rx, ry, e["name"])] = e

actual_keys = set()
for r in actual:
    actual_keys.add((round(r["x"], 1), round(r["y"], 1), r["type"]))

missing = set(expected_keys.keys()) - actual_keys
extra = actual_keys - set(expected_keys.keys())

print()
print(f"Missing (expected, not found in game): {len(missing)}")
print(f"Extra (in game, not in blueprint - duplicates or unrelated): {len(extra)}")

by_type = {}
for rx, ry, t in missing:
    by_type[t] = by_type.get(t, 0) + 1
print("Missing by type:", by_type)

manifest = []
for key in missing:
    rx, ry, name = key
    e = expected_keys[key]
    manifest.append({"name": name, "x": rx, "y": ry, "entity_number": e["entity_number"], "raw": e})

with open("census_300_missing.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f)
print(f"\nWrote census_300_missing.json with {len(manifest)} entries")

if extra:
    extra_sample = sorted(extra)[:20]
    print("\nExtra sample (first 20):", extra_sample)
