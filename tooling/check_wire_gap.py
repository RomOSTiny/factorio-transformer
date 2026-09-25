import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
wires = bp.get("wires", [])

# entities #399 and #400 (path indices 40 and 41)
relevant = [w for w in wires if 399 in (w[0],w[2]) or 400 in (w[0],w[2])]
print("wires touching #399 or #400:")
for w in relevant:
    print(" ", w)
