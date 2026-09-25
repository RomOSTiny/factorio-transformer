import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]

gates = [e for e in entities if e["name"] == "decider-combinator"
         and len(e.get("control_behavior", {}).get("decider_conditions", {}).get("conditions", [])) == 2]
gates.sort(key=lambda e: e["position"]["x"])
print("gate count:", len(gates))
for g in gates[:3] + gates[-2:]:
    dc = g["control_behavior"]["decider_conditions"]
    print(g["position"], json.dumps(dc, ensure_ascii=False))

tmod = next(e for e in entities if e["name"] == "arithmetic-combinator"
            and e.get("control_behavior", {}).get("arithmetic_conditions", {}).get("output_signal", {}).get("name") == "signal-M"
            and e["control_behavior"]["arithmetic_conditions"].get("first_signal", {}).get("name") == "signal-T")
print("tmod:", tmod["position"], json.dumps(tmod["control_behavior"]["arithmetic_conditions"], ensure_ascii=False))

addr = next(e for e in entities if e["name"] == "arithmetic-combinator"
            and e.get("control_behavior", {}).get("arithmetic_conditions", {}).get("output_signal", {}).get("name") == "signal-N"
            and e["control_behavior"]["arithmetic_conditions"].get("first_signal", {}).get("name") == "signal-T")
print("addr:", addr["position"], json.dumps(addr["control_behavior"]["arithmetic_conditions"], ensure_ascii=False))
