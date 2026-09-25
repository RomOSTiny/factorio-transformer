import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()

raw = base64.b64decode(s[1:])  # skip version byte
data = json.loads(zlib.decompress(raw))

entities = data["blueprint"]["entities"]
deciders = [e for e in entities if e["name"] == "decider-combinator"]
print(f"total decider-combinators: {len(deciders)}")

# find gate_0: lowest x among deciders with control_behavior conditions referencing signal-O
gate_candidates = []
for e in deciders:
    cb = e.get("control_behavior", {})
    dc = cb.get("decider_conditions", cb.get("conditions"))
    entry = {"position": e["position"], "control_behavior": cb}
    gate_candidates.append(entry)

# sort by x to find gate_0 (leftmost)
gate_candidates.sort(key=lambda e: e["position"]["x"])
for g in gate_candidates[:3]:
    print(json.dumps(g, indent=2))
