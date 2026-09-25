import json
import shutil

shutil.copy(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\matmul_diag2.json", "matmul_diag2.json")

with open("matmul_diag2.json", encoding="utf-8-sig") as f:
    ents = json.load(f)

print("total entities found:", len(ents))
BX, BY = 600, 600


def key(e):
    return e["type"], e["x"], e["y"]


for e in sorted(ents, key=key):
    sig = e.get("circuit") or e.get("output") or []
    tag = "circuit" if "circuit" in e else "output"
    marker = "  " if sig else "**EMPTY**"
    print(f"{marker} ({e['x']-BX:6.1f},{e['y']-BY:6.1f}) {e['type']:22s} [{tag}]: {sig}")
