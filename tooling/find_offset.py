import json

from draftsman.classes.blueprint import Blueprint

with open("stage2_matmul_test_blueprint.txt") as f:
    bp = Blueprint.from_string(f.read())

expected = {}
for e in bp.entities:
    if e.name == "constant-combinator":
        vals = tuple(sorted((s.name, s.count) for s in e.sections[0].filters.values()))
        expected.setdefault(vals, []).append((e.id, e.tile_position[0] + 0.5, e.tile_position[1] + 0.5))

with open("matmul_diag2.json", encoding="utf-8-sig") as f:
    real = json.load(f)

real_const = [e for e in real if e["type"] == "constant-combinator" and e.get("circuit")]
print(f"Real constants with nonzero signal: {len(real_const)}")

# find a value combo that's UNIQUE in the expected set (appears at exactly one local position)
unique_targets = {k: v for k, v in expected.items() if len(v) == 1}
print(f"Unique-valued expected constants: {len(unique_targets)} / {len(expected)}")

matches = []
for e in real_const:
    vals = tuple(sorted((s["name"], s["count"]) for s in e["circuit"]))
    if vals in unique_targets:
        eid, lx, ly = unique_targets[vals][0]
        offset_x = e["x"] - lx
        offset_y = e["y"] - ly
        matches.append((eid, lx, ly, e["x"], e["y"], offset_x, offset_y))

print(f"\nMatched {len(matches)} unique constants:")
for m in matches[:15]:
    print(f"  id={m[0]:12s} local=({m[1]:.1f},{m[2]:.1f}) real=({m[3]:.1f},{m[4]:.1f}) offset=({m[5]:.2f},{m[6]:.2f})")

if matches:
    ox = sum(m[5] for m in matches) / len(matches)
    oy = sum(m[6] for m in matches) / len(matches)
    print(f"\nAverage offset: ({ox:.2f}, {oy:.2f})")

    # locate t_ctr precisely
    for e in bp.entities:
        if e.id == "t_ctr":
            tx, ty = e.position["x"] if isinstance(e.position, dict) else e.position[0], e.position["y"] if isinstance(e.position, dict) else e.position[1]
            print(f"t_ctr local position: ({tx:.2f},{ty:.2f}) -> expected absolute: ({tx+ox:.2f},{ty+oy:.2f})")
