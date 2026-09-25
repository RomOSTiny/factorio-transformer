"""Revive all ghosts in an area, in passes over ALL ghosts (slices of BATCH per RCON call).

usage: live_revive_batched.py X Y [HX HY]
A pass tries every remaining ghost once (some fail because of overlapping ghosts / not-yet-real
neighbours); passes repeat until a full pass revives nothing. The old version re-tried only the
first 400 ghosts and stalled when >400 were unrevivable.
"""
import sys
sys.path.insert(0, r"C:\Users\roma_\Desktop\factorio-ai\tooling")
from rcon_client import connect

PX, PY = float(sys.argv[1]), float(sys.argv[2])
HX = float(sys.argv[3]) if len(sys.argv) > 3 else 280
HY = float(sys.argv[4]) if len(sys.argv) > 4 else 440
BATCH = 400

AREA = f"{{{{{PX-HX},{PY-HY}}},{{{PX+HX},{PY+HY}}}}}"
count_lua = f'''
local surf = game.surfaces["nauvis"]
rcon.print(tostring(surf.count_entities_filtered{{area={AREA}, type="entity-ghost"}}))
'''


def run(lua):
    with connect(timeout=120) as c:
        return c.command("/c " + " ".join(lua.split("\n"))).strip()


remaining = int(run(count_lua))
print("ghosts before:", remaining)
for pas in range(60):
    revived_pass = 0
    skip = 0
    while True:
        lua = f'''
local surf = game.surfaces["nauvis"]
local g = surf.find_entities_filtered{{area={AREA}, type="entity-ghost"}}
local n, tried = 0, 0
for i={skip + 1},math.min(#g, {skip + BATCH}) do
  tried = tried + 1
  if g[i].valid and g[i].revive() then n = n + 1 end
end
rcon.print(n .. "," .. tried .. "," .. #g)
'''
        n, tried, total = map(int, run(lua).split(","))
        revived_pass += n
        skip += tried - n
        if skip >= total - n or tried == 0:
            break
    remaining = int(run(count_lua))
    print(f"pass {pas}: revived {revived_pass}, remaining {remaining}")
    if revived_pass == 0 or remaining == 0:
        break
print("DONE reviving at", PX, PY, "remaining", remaining)
