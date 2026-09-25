"""
Exports every intended wire connection (position1, connector1, position2,
connector2) from the current export_full.py build, in REAL in-game
coordinates, so a small in-game script can verify/recreate any that failed
to form during mass ghost revival (confirmed via GUI: some ghost-to-ghost
circuit connections don't survive scripted entity.revive() at this scale -
input side showed connected, output side showed "not connected" despite
being correctly specified in the blueprint's own wire data).

Usage: edit PURE_OFFSET below to match the current world's paste position
(same landmark technique used throughout this debug session - read the
4 known TEST_INPUT constant-combinator signal-check values back from a
fresh factorio_ai_debug.json dump and solve for the offset), then run.
Writes wire_repair.json directly into Factorio's script-output folder.
"""
import io
import contextlib
import json
import os

PURE_OFFSET = (-61.0, -135.0)  # UPDATE if the world/paste position changes

g = {"__name__": "__not_main__"}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(compile(open("export_full.py").read(), "export_full.py", "exec"), g)

bp = g["bp"]

TYPE_OFFSET = {
    "constant-combinator": (0.5, 0.5),
    "arithmetic-combinator": (0.5, 1.0),
    "decider-combinator": (0.5, 1.0),
    "electric-pole": (0.5, 0.5),  # medium-electric-pole; substation handled via .position directly below
}

by_id = {e.id: e for e in bp.entities}


def real_pos(e):
    # prefer true .position when available (substations/poles were placed
    # via position= directly) - fall back to tile_position + type offset
    # for arithmetic/decider/constant, which were placed via tile_position=
    if e.name == "substation":
        p = e.position
        px, py = (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])
        return (round(px + PURE_OFFSET[0], 2), round(py + PURE_OFFSET[1], 2))
    if e.name == "medium-electric-pole":
        p = e.position
        px, py = (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])
        return (round(px + PURE_OFFSET[0], 2), round(py + PURE_OFFSET[1], 2))
    p = e.tile_position

    tx, ty = (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])
    tox, toy = TYPE_OFFSET.get(e.name, (0.5, 0.5))
    return (round(tx + tox + PURE_OFFSET[0], 2), round(ty + toy + PURE_OFFSET[1], 2))


from draftsman.classes.association import Association

edges = []
for w in bp.wires:
    e1, c1, e2, c2 = w
    n1 = e1() if isinstance(e1, Association) else e1
    n2 = e2() if isinstance(e2, Association) else e2
    c1v = c1.value if hasattr(c1, "value") else c1
    c2v = c2.value if hasattr(c2, "value") else c2
    p1 = real_pos(n1)
    p2 = real_pos(n2)
    edges.append([p1[0], p1[1], c1v, p2[0], p2[1], c2v])

out_path = os.path.expandvars(r"%APPDATA%\Factorio\script-output\wire_repair.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(edges, f)

print(f"Wrote {len(edges)} wire edges to {out_path}")
