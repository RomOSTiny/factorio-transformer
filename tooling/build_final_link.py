import json
import math

exec(open("build_letter_input_power.py").read().split("cmd = build_lua()")[0])

status = json.load(open(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\lin_sub_status.json", encoding="utf-8"))
real_pos = {d["id"]: (d["real_x"], d["real_y"]) for d in status}
assert len(real_pos) == 39, len(real_pos)

# rebuild sub_lattice's (r,c)->id mapping to redo the neighbor-link pass
# using REAL positions instead of originally-planned ones
id_to_rc = {}
for (r, c), (sid, x, y) in sub_lattice.items():
    id_to_rc[sid] = (r, c)

real_sub_links = []
for (r, c), (sid, x, y) in sub_lattice.items():
    for nr, nc in ((r, c + 1), (r + 1, c)):
        nxt = sub_lattice.get((nr, nc))
        if nxt:
            nid = nxt[0]
            real_sub_links.append((sid, nid))

ex, ey = nearest_existing
closest_new_id = max(real_pos.items(), key=lambda kv: kv[1][1])[0]  # id with y nearest -343 (least negative)
real_sub_links.append((closest_new_id, "EXISTING"))

print(f"Links to make: {len(real_sub_links)}")

parts = ['/c local surf=game.player.surface; local id_lookup={}; ']
parts.append(f'id_lookup["EXISTING"]=surf.find_entities_filtered{{name="substation",position={{{ex},{ey}}},radius=0.5}}[1]; ')
for sid, (x, y) in real_pos.items():
    parts.append(f'id_lookup["{sid}"]=surf.find_entities_filtered{{name="substation",position={{{x},{y}}},radius=0.3}}[1]; ')

parts.append('local linked,lfail,failed_links=0,0,{}; ')
for id1, id2 in real_sub_links:
    parts.append(
        f'do local ok=pcall(function() local w1=id_lookup["{id1}"].get_wire_connector(5,true); local w2=id_lookup["{id2}"].get_wire_connector(5,true); w1.connect_to(w2,false,defines.wire_origin.script) end); '
        f'if ok then linked=linked+1 else lfail=lfail+1; failed_links[#failed_links+1]="{id1}--{id2}" end end; '
    )
parts.append('game.print("FINAL power link: linked="..linked..", failed="..lfail); for _,f in pairs(failed_links) do game.print("FAILED: "..f) end')

cmd = "".join(parts)
with open("final_power_link.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(f"{len(cmd)} chars")
