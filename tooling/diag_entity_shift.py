import json, ast

OX, OY = 423.0, 290.0
census = json.load(open(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\matmul_census.json", encoding="utf-8"))

with open("repair_entities.lua_data") as f:
    raw = f.read().strip()
D = ast.literal_eval(raw.replace("{", "[").replace("}", "]").replace("nil", "None"))
print("entity entries:", len(D))

def nearest(x, y):
    best, bd = None, 1e18
    for e in census:
        d = max(abs(e["x"] - x), abs(e["y"] - y))
        if d < bd:
            bd, best = d, e
    return best, bd

int_x_count = 0
narrow_miss = 0  # would have been "not found" under the old 0.4 radius
examples = []
for d in D:
    _, x, y = d[0], d[1], d[2]
    wx, wy = x + OX, y + OY
    if x == int(x):
        int_x_count += 1
    e, dist = nearest(wx, wy)
    if dist > 0.4:
        narrow_miss += 1
        if len(examples) < 10:
            examples.append((x, y, wx, wy, dist, e))

print("entries with integer local x:", int_x_count)
print("entries that would MISS under old 0.4 radius (dist>0.4 to nearest real entity):", narrow_miss)
for ex in examples:
    print(ex)
