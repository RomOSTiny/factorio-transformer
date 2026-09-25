import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()

raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
entities = data["blueprint"]["entities"]
deciders = [e for e in entities if e["name"] == "decider-combinator"]

# find a read_i style decider (1 condition, output signal-W or signal-X)
single_cond = [e for e in deciders if len(e.get("control_behavior",{}).get("decider_conditions",{}).get("conditions",[])) == 1]
print(f"single-condition deciders: {len(single_cond)}")
print(json.dumps(single_cond[0]["control_behavior"], indent=2))
print()
print(json.dumps(single_cond[5]["control_behavior"], indent=2))
