"""Repair pass #2 for the 269 genuinely-missing arithmetic-combinators.

Root cause (confirmed via occupancy check): 251/269 target positions are
blocked by an already-real neighbor -- this is the project's known
"order-dependent revival collision" class of bug (an already-revived
neighbor's position, after Factorio's own build-time positioning, ends up
just close enough to block a not-yet-revived ghost). Since the blocking
neighbors are now permanent real entities, we can't rebuild via ghosts at
the exact target -- instead try create_entity at the exact (offset-
corrected) target, and on collision (nil result) try small perturbations
until one clears, recording how far each entity had to move (the later
wire-repair step tolerates up to ~0.6 tiles of drift when matching
blueprint wire endpoints to real entities).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

OX, OY = -2427.5 - 0.5, -299.5 - 0.5  # empirically-confirmed correction for arithmetic-combinator
BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_layernorm_full_test_blueprint.txt")
MISSING_PATH = os.path.join(os.path.dirname(__file__), "scratch_truly_missing3.json")

bp_string = open(BLUEPRINT_PATH, encoding="utf-8").read().strip()
bp = get_blueprintable_from_string(bp_string)
arith = [e for e in bp.entities if e.name == "arithmetic-combinator"]
missing = json.load(open(MISSING_PATH, encoding="utf-8"))

manifest = []
for m in missing:
    e = arith[m["idx"]]
    d = e.to_dict()["control_behavior"]["arithmetic_conditions"]
    manifest.append({"x": e.position.x + OX, "y": e.position.y + OY, "cb": d})

manifest_json = json.dumps(manifest)
print(f"manifest entries: {len(manifest)}, json size: {len(manifest_json)}")

lua = '''
local surf = game.surfaces["nauvis"]
local force = game.forces["player"]
local manifest = helpers.json_to_table("__MANIFEST__")
local offsets = {{0,0},{0.2,0},{-0.2,0},{0,0.2},{0,-0.2},{0.2,0.2},{-0.2,-0.2},{0.2,-0.2},{-0.2,0.2},{0.3,0},{-0.3,0},{0,0.3},{0,-0.3}}
local created, failed, nudged = 0, 0, 0
local fail_list = {}
for _, item in pairs(manifest) do
  local done = false
  for _, off in pairs(offsets) do
    local px, py = item.x + off[1], item.y + off[2]
    local ok, ent = pcall(function()
      return surf.create_entity{name="arithmetic-combinator", position={px, py}, force=force, raise_built=false}
    end)
    if ok and ent then
      ent.get_or_create_control_behavior().parameters = item.cb
      created = created + 1
      if off[1] ~= 0 or off[2] ~= 0 then nudged = nudged + 1 end
      done = true
      break
    end
  end
  if not done then
    failed = failed + 1
    table.insert(fail_list, item.x .. "," .. item.y)
  end
end
helpers.write_file("repair2.json", helpers.table_to_json({created=created, failed=failed, nudged=nudged, fail_list=fail_list}), false)
rcon.print("created=" .. created .. " nudged=" .. nudged .. " failed=" .. failed)
'''.strip()

lua = lua.replace("__MANIFEST__", manifest_json.replace("\\", "\\\\").replace('"', '\\"'))

with connect(timeout=60.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
