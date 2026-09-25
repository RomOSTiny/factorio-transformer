import json

with open("matmul_diag_pretty.json", encoding="utf-8-sig") as f:
    d = json.load(f)
print("ghosts_remaining:", d["ghosts_remaining"])
ents = d["entities"]
print("total entities found:", len(ents))
nonzero = [e for e in ents if e["output"]]
print("entities with nonzero output:", len(nonzero))
for e in sorted(nonzero, key=lambda e: (e["x"], e["y"])):
    print(f"  ({e['x']-600:.1f},{e['y']-600:.1f}) {e['type']}: {e['output']}")

zero = [e for e in ents if not e["output"]]
print(f"\nentities with EMPTY output: {len(zero)}")
for e in sorted(zero, key=lambda e: (e["x"], e["y"]))[:20]:
    print(f"  ({e['x']-600:.1f},{e['y']-600:.1f}) {e['type']}")
