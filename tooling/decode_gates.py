import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()

raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
entities = data["blueprint"]["entities"]
deciders = [e for e in entities if e["name"] == "decider-combinator"]

gates = []
for e in deciders:
    dc = e.get("control_behavior", {}).get("decider_conditions", {})
    conds = dc.get("conditions", [])
    outs = dc.get("outputs", [])
    if len(conds) == 2 and outs and outs[0].get("signal", {}).get("name") == "signal-P":
        gates.append((e["position"]["x"], e["position"]["y"], conds, outs))

gates.sort(key=lambda g: g[0])
print(f"found {len(gates)} gate_j candidates")
for i, (x, y, conds, outs) in enumerate(gates):
    print(f"--- gate_{i} at ({x},{y}) ---")
    for c in conds:
        print(f"  cond: first={c.get('first_signal')} comparator={c.get('comparator')!r} constant={c.get('constant')} compare_type={c.get('compare_type')}")
    print(f"  output: {outs[0]}")
