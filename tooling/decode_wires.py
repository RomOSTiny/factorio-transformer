import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()

raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]
wires = bp.get("wires", [])
print(f"total entities: {len(entities)}, total wires: {len(wires)}")

by_num = {e["entity_number"]: e for e in entities}

# find gate_0: decider at x=150.5,y=421.0 (from earlier scan)
gate0 = next(e for e in entities if e["name"]=="decider-combinator" and e["position"]["x"]==150.5 and e["position"]["y"]==421.0)
acc0 = next(e for e in entities if e["name"]=="arithmetic-combinator" and e["position"]["x"]==152.5 and abs(e["position"]["y"]-421.0)<0.01)
print("gate0 entity_number:", gate0["entity_number"], "pos", gate0["position"])
print("acc0 entity_number:", acc0["entity_number"], "pos", acc0["position"])

gate0_wires = [w for w in wires if gate0["entity_number"] in (w[0], w[2])]
print(f"\nwires touching gate0 ({len(gate0_wires)}):")
for w in gate0_wires:
    print(" ", w)

acc0_wires = [w for w in wires if acc0["entity_number"] in (w[0], w[2])]
print(f"\nwires touching acc0 ({len(acc0_wires)}):")
for w in acc0_wires:
    print(" ", w)
