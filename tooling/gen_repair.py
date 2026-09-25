import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]
wires = bp.get("wires", [])
by_num = {e["entity_number"]: e for e in entities}

relevant_types = {"arithmetic-combinator", "decider-combinator"}
lines = []
for w in wires:
    e1, c1, e2, c2 = w
    ent1, ent2 = by_num[e1], by_num[e2]
    if ent1["name"] not in relevant_types or ent2["name"] not in relevant_types:
        continue
    p1 = ent1["position"]
    p2 = ent2["position"]
    lines.append(f"{{{p1['x']},{p1['y']},{c1},{p2['x']},{p2['y']},{c2}}}")

print(f"total arith/decider wires: {len(lines)}")
lua_array = "{" + ",".join(lines) + "}"
with open("repair_wires.lua_data", "w") as f:
    f.write(lua_array)
print("bytes:", len(lua_array))
