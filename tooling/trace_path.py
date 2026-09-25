import base64, zlib, json
from collections import deque

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]
wires = bp.get("wires", [])
by_num = {e["entity_number"]: e for e in entities}

out_idx = next(e for e in entities if e["name"]=="arithmetic-combinator" and e.get("control_behavior",{}).get("arithmetic_conditions",{}).get("output_signal",{}).get("name")=="signal-O")
gate_nums = [e["entity_number"] for e in entities if e["name"]=="decider-combinator" and len(e.get("control_behavior",{}).get("decider_conditions",{}).get("conditions",[]))==2]
gate0_num = min(gate_nums, key=lambda n: by_num[n]["position"]["x"])

green_wires = [w for w in wires if w[1] in (2,4) and w[3] in (2,4)]
adj = {}
for w in green_wires:
    adj.setdefault(w[0], []).append(w[2])
    adj.setdefault(w[2], []).append(w[0])

# BFS shortest path from out_idx to gate0
start = out_idx["entity_number"]
parent = {start: None}
q = deque([start])
while q:
    n = q.popleft()
    if n == gate0_num:
        break
    for nb in adj.get(n, []):
        if nb not in parent:
            parent[nb] = n
            q.append(nb)

path = []
n = gate0_num
while n is not None:
    path.append(n)
    n = parent.get(n)
path.reverse()

print(f"path length: {len(path)}")
for i, num in enumerate(path):
    e = by_num[num]
    print(f"{i}: #{num} {e['name']} @({e['position']['x']},{e['position']['y']})")
