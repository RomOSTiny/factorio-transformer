import io
import contextlib
import json

PURE_OFFSET = (-61.0, -135.0)

g = {"__name__": "__not_main__"}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(compile(open("export_full.py").read(), "export_full.py", "exec"), g)

bp = g["bp"]
from draftsman.classes.association import Association

TYPE_OFFSET = {
    "constant-combinator": (0.5, 0.5),
    "arithmetic-combinator": (0.5, 1.0),
    "decider-combinator": (0.5, 1.0),
}


def real_pos(e):
    p = e.tile_position
    tx, ty = (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])
    tox, toy = TYPE_OFFSET[e.name]
    return (round(tx + tox + PURE_OFFSET[0], 1), round(ty + toy + PURE_OFFSET[1], 1))


id_to_real = {}
real_to_id = {}
for e in bp.entities:
    if e.name not in TYPE_OFFSET:
        continue
    rp = real_pos(e)
    id_to_real[e.id] = rp
    real_to_id[rp] = e.id

with open(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\broken_outputs3.json", encoding="utf-8") as f:
    broken = json.load(f)

broken_ids = []
unmatched = []
for b in broken:
    rp = (round(b["x"], 1), round(b["y"], 1))
    bid = real_to_id.get(rp)
    if bid:
        broken_ids.append(bid)
    else:
        unmatched.append(b)

print(f"Matched {len(broken_ids)}/{len(broken)} broken entities to blueprint ids")
if unmatched:
    print("unmatched:", unmatched)

broken_id_set = set(broken_ids)

# this time: include every wire edge touching a broken entity on EITHER
# side (newly-created entities have NO connections at all yet, not just a
# missing output side) - dedupe since an edge between two broken entities
# would otherwise be found from both directions
seen_edges = set()
repair_edges = []
for w in bp.wires:
    e1, c1, e2, c2 = w
    n1 = e1() if isinstance(e1, Association) else e1
    n2 = e2() if isinstance(e2, Association) else e2
    c1v = c1.value if hasattr(c1, "value") else c1
    c2v = c2.value if hasattr(c2, "value") else c2
    if n1.id not in id_to_real or n2.id not in id_to_real:
        continue
    if n1.id in broken_id_set or n2.id in broken_id_set:
        key = tuple(sorted([(n1.id, c1v), (n2.id, c2v)]))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        repair_edges.append((id_to_real[n1.id][0], id_to_real[n1.id][1], c1v, id_to_real[n2.id][0], id_to_real[n2.id][1], c2v))

print(f"Repair edges needed: {len(repair_edges)}")

BATCH_SIZE = 40
chunks = [repair_edges[i : i + BATCH_SIZE] for i in range(0, len(repair_edges), BATCH_SIZE)]

for b, chunk in enumerate(chunks):
    parts = [f"{{{x1},{y1},{c1},{x2},{y2},{c2}}}" for x1, y1, c1, x2, y2, c2 in chunk]
    lua_table = "{" + ",".join(parts) + "}"
    command = (
        "/c local edges=" + lua_table + "; "
        "local surf=game.player.surface; "
        "local lookup={}; "
        'local function key(x,y) return string.format("%.1f,%.1f", x, y) end; '
        'local ents=surf.find_entities_filtered{type={"arithmetic-combinator","decider-combinator","constant-combinator"}}; '
        "for _,e in pairs(ents) do lookup[key(e.position.x, e.position.y)]=e end; "
        "local created,missing=0,0; "
        "for _,edge in pairs(edges) do "
        "local e1=lookup[key(edge[1],edge[2])]; local e2=lookup[key(edge[4],edge[5])]; "
        "if e1 and e2 then "
        "local ok1,wc1=pcall(function() return e1.get_wire_connector(edge[3], true) end); "
        "local ok2,wc2=pcall(function() return e2.get_wire_connector(edge[6], true) end); "
        "if ok1 and ok2 and wc1 and wc2 then wc1.connect_to(wc2, false, defines.wire_origin.script) created=created+1 end "
        "else missing=missing+1 end end; "
        f'game.print("wire repair batch {b+1}/{len(chunks)}: created="..created..", missing_entities="..missing.."/"..#edges)'
    )
    with open(f"wire_repair_batch_{b+1}.txt", "w", encoding="utf-8") as f:
        f.write(command)
    non_ascii = sum(1 for ch in command if ord(ch) > 127)
    print(f"batch {b+1}: {len(command)} chars, {len(chunk)} edges, non-ascii={non_ascii}")
