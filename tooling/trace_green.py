import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]
wires = bp.get("wires", [])
by_num = {e["entity_number"]: e for e in entities}

def desc(e):
    cb = e.get("control_behavior", {})
    p = cb.get("arithmetic_conditions", {})
    tag = ""
    if p:
        tag = f"{p.get('first_signal',{}).get('name')} {p.get('operation')} {p.get('second_signal',{}).get('name', p.get('second_constant'))} -> {p.get('output_signal',{}).get('name')}"
    return f"#{e['entity_number']} {e['name']} @({e['position']['x']},{e['position']['y']}) [{tag}]"

# find out_idx: first_signal N, operation /, second_constant 5, output O
out_idx = next(e for e in entities if e["name"]=="arithmetic-combinator" and e.get("control_behavior",{}).get("arithmetic_conditions",{}).get("output_signal",{}).get("name")=="signal-O")
print("out_idx:", desc(out_idx))

# BFS along GREEN wires only (connector 2=in_green, 4=out_green) starting from out_idx
green_wires = [w for w in wires if w[1] in (2,4) and w[3] in (2,4)]
print(f"total green wires: {len(green_wires)}")

visited = {out_idx["entity_number"]}
frontier = [out_idx["entity_number"]]
path_edges = []
for _ in range(200):
    new_frontier = []
    for n in frontier:
        for w in green_wires:
            other = None
            if w[0]==n: other=w[2]
            elif w[2]==n: other=w[0]
            if other is not None and other not in visited:
                visited.add(other)
                new_frontier.append(other)
                path_edges.append(w)
    if not new_frontier:
        break
    frontier = new_frontier

print(f"total reached via green from out_idx: {len(visited)}")
gate_nums = [e["entity_number"] for e in entities if e["name"]=="decider-combinator" and len(e.get("control_behavior",{}).get("decider_conditions",{}).get("conditions",[]))==2]
gate0_num = min(gate_nums, key=lambda n: by_num[n]["position"]["x"])
print("gate0 entity_number:", gate0_num, "reached?", gate0_num in visited)
