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

OX, OY = -172.0, 151.0

# find v_local: arithmetic-combinator at local (245.0, 298.0)
target = None
for e in entities:
    if e["name"] == "arithmetic-combinator" and abs(e["position"]["x"] - 245.0) < 0.01 and abs(e["position"]["y"] - 298.0) < 0.01:
        target = e
        break
print("v_local entity_number:", target["entity_number"], "local pos:", target["position"])

for w in wires:
    e1, c1, e2, c2 = w
    if e1 == target["entity_number"] or e2 == target["entity_number"]:
        other = by_num[e2] if e1 == target["entity_number"] else by_num[e1]
        my_c = c1 if e1 == target["entity_number"] else c2
        other_c = c2 if e1 == target["entity_number"] else c1
        ox, oy = other["position"]["x"] + OX, other["position"]["y"] + OY
        print(f"  wire: v_local cid={my_c} <-> {other['name']}#{other['entity_number']} cid={other_c} at world({ox},{oy}) local({other['position']})")
