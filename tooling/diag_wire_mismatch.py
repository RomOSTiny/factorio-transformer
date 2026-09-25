import json

OX, OY = 423.0, 290.0

census = json.load(open(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\matmul_census.json", encoding="utf-8"))
print("census count:", len(census))

# build simple nearest-lookup (per-axis max, matching find_near's per-axis check)
def nearest(x, y):
    best, bd = None, 1e18
    for e in census:
        d = max(abs(e["x"] - x), abs(e["y"] - y))
        if d < bd:
            bd, best = d, e
    return best, bd

import ast
with open("repair_wires.lua_data") as f:
    raw = f.read().strip()
W = ast.literal_eval(raw.replace("{", "[").replace("}", "]"))
print("wire tuples:", len(W))

miss_examples = []
n_missing = 0
for w in W:
    x1, y1, c1, x2, y2, c2 = w
    wx1, wy1 = x1 + OX, y1 + OY
    wx2, wy2 = x2 + OX, y2 + OY
    e1, d1 = nearest(wx1, wy1)
    e2, d2 = nearest(wx2, wy2)
    bad = d1 > 0.6 or d2 > 0.6
    if bad:
        n_missing += 1
        if len(miss_examples) < 15:
            miss_examples.append((x1, y1, c1, x2, y2, c2, wx1, wy1, d1, wx2, wy2, d2))

print("missing (dist>0.05):", n_missing, "/", len(W))
print()
for m in miss_examples:
    x1, y1, c1, x2, y2, c2, wx1, wy1, d1, wx2, wy2, d2 = m
    print(f"local ({x1},{y1},c{c1}) -> world ({wx1},{wy1}) dist={d1:.3f}   |   local ({x2},{y2},c{c2}) -> world ({wx2},{wy2}) dist={d2:.3f}")
