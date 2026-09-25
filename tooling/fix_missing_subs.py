import json

missing = [
    ("lin_sub_1_8", 100, -392),
    ("lin_sub_2_8", 100, -377),
    ("lin_sub_3_8", 100, -368),
    ("lin_sub_4_8", 100, -353),
]

# try a spread of nearby integer offsets, pushing away from the tight
# read/write column gap at x=99.5-100.5 (widen mainly in x, small y spread too)
CANDIDATES = [(0, 0), (3, 0), (-3, 0), (0, 3), (0, -3), (4, 2), (4, -2), (-4, 2), (-4, -2), (6, 0), (-6, 0)]

parts = ['/c local force=game.player.force; local surf=game.player.surface; local created,failed=0,0; local results={}; ']
for sid, x, y in missing:
    tries = []
    for dx, dy in CANDIDATES:
        tries.append(f'if not id then local e=surf.create_entity{{name="substation",position={{{x+dx},{y+dy}}},force=force,quality="legendary",raise_built=false}}; if e then id=e end end')
    body = "; ".join(tries)
    parts.append(f'do local id=nil; {body}; if id then created=created+1; results[#results+1]="{sid} -> ("..id.position.x..","..id.position.y..")" else failed=failed+1; results[#results+1]="{sid} FAILED ALL CANDIDATES" end end; ')

parts.append('game.print("created="..created..", failed="..failed); for _,r in pairs(results) do game.print(r) end')
cmd = "".join(parts)
with open("fix_missing_subs.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "chars")
