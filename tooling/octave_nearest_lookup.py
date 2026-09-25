import base64
import zlib
import json

with open("stage2_octave_isolated_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
entities = data["blueprint"]["entities"]
OX, OY = -172.0, 151.0
targets = [(172.5, 146), (147.5, 185), (117.5, 230), (79.5, 288), (110.5, 409), (79.5, 540)]
for tx, ty in targets:
    lx, ly = tx - OX, ty - OY
    best = min(entities, key=lambda e: (e["position"]["x"] - lx) ** 2 + (e["position"]["y"] - ly) ** 2)
    d = ((best["position"]["x"] - lx) ** 2 + (best["position"]["y"] - ly) ** 2) ** 0.5
    name = best["name"]
    num = best["entity_number"]
    pos = best["position"]
    print(f"target world=({tx},{ty}) local=({lx:.2f},{ly:.2f}) -> nearest blueprint #{num} {name} at local {pos} dist={d:.3f}")
