"""
Manifest generator for the octave test's repair pipeline - same technique
as gen_repair_entities.py/gen_repair.py (decode the blueprint string locally,
base64->zlib->json, extract every arithmetic/decider entity + wire pair as a
compact Lua data literal) just repointed at this session's blueprint file.
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

relevant_types = {"arithmetic-combinator", "decider-combinator"}

lines = []
for e in entities:
    if e["name"] != "arithmetic-combinator":
        continue
    p = e["position"]
    ac = e.get("control_behavior", {}).get("arithmetic_conditions", {})
    fs = ac.get("first_signal", {}).get("name", "")
    op = ac.get("operation", "*")
    sc = ac.get("second_signal")
    sc_name = sc.get("name") if sc else None
    sconst = ac.get("second_constant", 0)
    os_ = ac.get("output_signal", {}).get("name", "")
    lines.append(f'{{1,{p["x"]},{p["y"]},"{fs}","{op}",{("\"" + sc_name + "\"") if sc_name else "nil"},{sconst},"{os_}"}}')
print(f"total arithmetic entries: {len(lines)}")
with open("octave_repair_entities.lua_data", "w") as f:
    f.write("{" + ",".join(lines) + "}")

wire_lines = []
for w in wires:
    e1, c1, e2, c2 = w
    ent1, ent2 = by_num[e1], by_num[e2]
    if ent1["name"] not in relevant_types or ent2["name"] not in relevant_types:
        continue
    p1, p2 = ent1["position"], ent2["position"]
    wire_lines.append(f"{{{p1['x']},{p1['y']},{c1},{p2['x']},{p2['y']},{c2}}}")
print(f"total arith/decider wires: {len(wire_lines)}")
with open("octave_repair_wires.lua_data", "w") as f:
    f.write("{" + ",".join(wire_lines) + "}")

print("bytes entities:", len(open("octave_repair_entities.lua_data").read()))
print("bytes wires:", len(open("octave_repair_wires.lua_data").read()))
