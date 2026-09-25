"""
Rebuilds circuit-wire connections that touch any of the 1306 entities
recreated by the entity repair pass (repair_300_manifest.json). Entities
that existed from the original revive() pass are assumed to already have
correct wires (per Решение 9's own finding, this ISN'T airtight - some
wire drops happened independent of entity-creation failures - but this is
the known-dominant case, and the final end-to-end phrase test will catch
anything this misses).

Rather than auditing which wires are ACTUALLY missing in-game (would need
LuaWireConnector.connections, an API this project hasn't exercised before
- real risk of guessing it wrong), this just reapplies every EXPECTED wire
touching a repaired entity unconditionally via connect_to() - reconnecting
an already-connected pair is a no-op in Factorio's wire model (connectors
store a SET, not a list), so this can't create duplicates or damage
already-correct wires.
"""

import base64
import json
import math
import zlib

BP_FILE = "export_full_300syl.txt"
DUMP_FILE = r"C:\Users\natas\AppData\Roaming\Factorio\script-output\factorio_ai_debug.json"
MANIFEST_FILE = "repair_300_manifest.json"

CENSUS_TYPES = {"constant-combinator", "arithmetic-combinator", "decider-combinator"}

with open(BP_FILE, "r") as f:
    s = f.read()
bp = json.loads(zlib.decompress(base64.b64decode(s[1:])))["blueprint"]
entities = bp["entities"]
wires = bp["wires"]
print(f"Total entities: {len(entities)}, total wires: {len(wires)}")

dump = json.load(open(DUMP_FILE, encoding="utf-8"))

# offset: same auto-detect as census_300.py
ex_xs = [e["position"]["x"] for e in entities if e["name"] in CENSUS_TYPES]
ex_ys = [e["position"]["y"] for e in entities if e["name"] in CENSUS_TYPES]
ac_xs = [r["x"] for r in dump if r["type"] in CENSUS_TYPES]
ac_ys = [r["y"] for r in dump if r["type"] in CENSUS_TYPES]
offset_x = min(ac_xs) - min(ex_xs)
offset_y = min(ac_ys) - min(ex_ys)
print(f"Offset: ({offset_x:.2f}, {offset_y:.2f})")

# entity_number (1-indexed, matches bp['wires'] references) -> real in-game
# position (rx, ry). NOTE: deliberately NOT resolving to unit_number here -
# game.get_entity_by_unit_number's exact Lua signature isn't something
# this project has actually exercised/confirmed before (unlike position-
# based lookup, which wire_repair_batch_1.txt from the previous session's
# repair already proved works: find_entities_filtered + a position-string
# lookup table). Reusing the proven pattern instead of risking a new,
# unverified API guess for what's meant to be a low-risk repair pass.
num_to_pos = {}
for e in entities:
    if e["name"] not in CENSUS_TYPES:
        continue
    rx = round(e["position"]["x"] + offset_x, 1)
    ry = round(e["position"]["y"] + offset_y, 1)
    num_to_pos[e["entity_number"]] = (rx, ry)
print(f"Resolved {len(num_to_pos)} entity_number -> position")

# which entity_numbers were repaired (position+name match against repair manifest)
manifest = json.load(open(MANIFEST_FILE, encoding="utf-8"))
repaired_positions = {(round(m["x"], 1), round(m["y"], 1), m["name"]) for m in manifest}

repaired_numbers = set()
for e in entities:
    if e["name"] not in CENSUS_TYPES:
        continue
    rx = round(e["position"]["x"] + offset_x, 1)
    ry = round(e["position"]["y"] + offset_y, 1)
    if (rx, ry, e["name"]) in repaired_positions:
        repaired_numbers.add(e["entity_number"])
print(f"Repaired entity count matched: {len(repaired_numbers)} (expect 1306)")

# filter wires touching a repaired entity - only wires between two
# CENSUS_TYPES entities are relevant here (skip power/pole wires, those
# use a different repair path already proven in export_full.py itself)
relevant_wires = []
for e1, c1, e2, c2 in wires:
    if e1 not in num_to_pos or e2 not in num_to_pos:
        continue  # not a combinator-to-combinator wire (e.g. touches a substation)
    if e1 in repaired_numbers or e2 in repaired_numbers:
        x1, y1 = num_to_pos[e1]
        x2, y2 = num_to_pos[e2]
        relevant_wires.append((x1, y1, c1, x2, y2, c2))

print(f"Wires touching a repaired entity: {len(relevant_wires)} (of {len(wires)} total)")

with open("wire_repair_300_pairs.json", "w") as f:
    json.dump(relevant_wires, f)

# ---- generate Lua batches - SAME proven pattern as the previous session's
# wire_repair_batch_1.txt: build a position-string -> entity lookup table
# fresh inside each batch command (via find_entities_filtered over all
# combinators), then resolve both endpoints of every edge through it. A
# little redundant to rebuild that lookup table once per batch rather than
# once total, but it's cheap (one scan over ~26k entities) next to the
# entity-repair pass this follows, and avoids introducing any new,
# unverified API call for what's meant to be the safe/proven repair path ----
PREAMBLE = (
    "local surf=game.player.surface; "
    'local function key(x,y) return string.format("%.1f,%.1f", x, y) end; '
    'local lookup={}; local ents=surf.find_entities_filtered{type={"arithmetic-combinator","decider-combinator","constant-combinator"}}; '
    "for _,e in pairs(ents) do lookup[key(e.position.x, e.position.y)]=e end; "
    "local created,missing=0,0; "
)
BODY_TEMPLATE = (
    "for _,edge in pairs(edges) do "
    "local e1=lookup[key(edge[1],edge[2])]; local e2=lookup[key(edge[4],edge[5])]; "
    "if e1 and e2 then "
    "local ok1,wc1=pcall(function() return e1.get_wire_connector(edge[3], true) end); "
    "local ok2,wc2=pcall(function() return e2.get_wire_connector(edge[6], true) end); "
    "if ok1 and ok2 and wc1 and wc2 then wc1.connect_to(wc2, false, defines.wire_origin.script) created=created+1 end "
    "else missing=missing+1 end end; "
)

BATCH_SIZE = 800

# each edge tuple is (x1,y1,c1,x2,y2,c2) - split relevant_wires, not the
# already-joined string, so batch boundaries land on whole edges
n_batches = math.ceil(len(relevant_wires) / BATCH_SIZE)
sizes = []
for b in range(n_batches):
    chunk = relevant_wires[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
    chunk_lua = ",".join(f"{{{x1},{y1},{c1},{x2},{y2},{c2}}}" for x1, y1, c1, x2, y2, c2 in chunk)
    cmd = (
        f"/c local edges={{{chunk_lua}}}; "
        + PREAMBLE
        + BODY_TEMPLATE
        + f'game.print("wire repair batch {b+1}/{n_batches}: created="..created..", missing_entities="..missing.."/"..#edges)'
    )
    with open(f"wire_repair300_batch_{b+1}.txt", "w", encoding="utf-8") as f:
        f.write(cmd)
    sizes.append(len(cmd))

print(f"Wrote {n_batches} wire-repair batches, sizes {min(sizes)}-{max(sizes)} chars")
