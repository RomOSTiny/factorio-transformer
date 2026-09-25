"""
Static (no game needed) check of the column-transition hypothesis for
Reshenie 32's two open bugs: build_addressed_rom's `hrelay` entities (the
horizontal broadcast spine that hands each column's address signal down
into that column's own vrelay chain) are built with `position=` (center-
anchored) using origin_x + col*COL_SPACING - which is an INTEGER for both
ROM instantiations (VROM_X=0, OLROM_X=250, COL_SPACING=4, all int). Every
OTHER position= call in stage2_octave_isolated_test.py was retroactively
patched with an explicit non-integer local X after Reshenie 26/this
session found that integer-local-X entities get a +0.5 shift at LIVE
placement while already-fractional ones (relay hops from bridge()) do not -
but build_addressed_rom itself (defined before that lesson, reused as-is)
was never patched. This script checks two things directly from the actual
built blueprint (no Factorio round-trip needed):
  1. What LOCAL position hrelay entities actually got exported at.
  2. What the blueprint's OWN wire list says hrelay should connect to,
     for the specific entities Reshenie 32 flagged: vrom hrelay_0/hrelay_1
     (value ROM, address 0's own column) and olrom hrelay_1/hrelay_2
     (oct_lower ROM, o=8's column), plus the col_collectors[1]->col_collectors[2]
     junction for both ROMs.
This does NOT prove the live bug by itself (revive()/repair can still drop
wires that the blueprint itself has correctly) - it only establishes
whether the BLUEPRINT's own intended wiring is already wrong (Python-side
bug) vs correct-on-paper-but-broken-live (repair-time bug), which changes
what the next live check needs to look for.
"""
import base64
import zlib
import json

with open("stage2_octave_isolated_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]
wires = bp.get("wires", [])
by_num = {e["entity_number"]: e for e in entities}

# entity_number doesn't carry draftsman's string id, so identify by nearest
# entity to the tile_position/position given in the source (search radius
# covers both combinator flavors - ArithmeticCombinator/DeciderCombinator
# are 1x2 (center = tile+(0.5,1.0)), ConstantCombinator is 1x1 (tile+0.5,0.5) -
# rather than guess which, just take the nearest entity within 1.5 tiles).
TARGETS = {
    "vrom_hrelay_0": (0.0, 90.0),
    "vrom_hrelay_1": (4.0, 90.0),
    "vrom_vrelay_0_0": (1.0, 92.0),
    "vrom_vrelay_0_1": (1.0, 100.0),
    "vrom_vrelay_1_0": (5.0, 92.0),
    "vrom_crelay_0_0": (3.0, 114.0),
    "vrom_crelay_0_1": (3.0, 106.0),  # col_collectors[0]
    "vrom_store_0": (0.0, 100.0),
    "vrom_read_0": (2.0, 100.0),
    "vrom_store_1": (0.0, 102.0),
    "vrom_read_1": (2.0, 102.0),
    "vrom_store_2": (0.0, 104.0),
    "vrom_read_2": (2.0, 104.0),
    "vrom_store_3": (0.0, 106.0),
    "vrom_read_3": (2.0, 106.0),
    "olrom_hrelay_1": (254.0, 140.0),
    "olrom_hrelay_2": (258.0, 140.0),
    "olrom_vrelay_2_0": (259.0, 142.0),
    "olrom_vrelay_2_1": (259.0, 150.0),
    "olrom_crelay_1_0": (257.0, 164.0),
    "olrom_crelay_1_1": (257.0, 156.0),  # col_collectors[1]
    "olrom_crelay_2_0": (261.0, 164.0),
    "olrom_crelay_2_1": (261.0, 156.0),  # col_collectors[2]
    "olrom_store_7": (254.0, 156.0),
    "olrom_read_7": (256.0, 156.0),
    "olrom_store_8": (258.0, 150.0),
    "olrom_read_8": (260.0, 150.0),
    "olrom_store_9": (258.0, 152.0),
    "olrom_read_9": (260.0, 152.0),
}

found = {}
print(f"{len(entities)} entities, {len(wires)} wires in blueprint\n")
for label, (ex, ey) in TARGETS.items():
    best, best_d = None, 999
    for e in entities:
        dx, dy = e["position"]["x"] - (ex + 0.5), e["position"]["y"] - (ey + 0.75)
        d = (dx * dx + dy * dy) ** 0.5
        if d < best_d:
            best, best_d = e, d
    if best is None or best_d > 1.5:
        print(f"{label:20s} @ expected tile {(ex, ey)} -> NOT FOUND nearby (best d={best_d:.2f})")
        continue
    found[label] = best
    print(f"{label:20s} entity#{best['entity_number']:4d} {best['name']:22s} local {best['position']}")

print("\n--- wires touching these entities ---")
for label, hit in found.items():
    num = hit["entity_number"]
    for w in wires:
        e1, c1, e2, c2 = w
        if e1 == num or e2 == num:
            other_num = e2 if e1 == num else e1
            my_c = c1 if e1 == num else c2
            other_c = c2 if e1 == num else c1
            other = by_num[other_num]
            other_label = next((l for l, h in found.items() if h["entity_number"] == other_num), None)
            other_desc = other_label if other_label else f"{other['name']}#{other_num}@{other['position']}"
            print(f"{label:20s} cid={my_c} <-> {other_desc} cid={other_c}")
