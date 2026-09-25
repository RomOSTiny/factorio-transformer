import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]

xs, ys = [], []
for e in entities:
    p = e["position"]
    xs.append(p["x"])
    ys.append(p["y"])

print("min_x", min(xs), "max_x", max(xs))
print("min_y", min(ys), "max_y", max(ys))
print("width", max(xs) - min(xs), "height", max(ys) - min(ys))
print("n_entities", len(entities))
