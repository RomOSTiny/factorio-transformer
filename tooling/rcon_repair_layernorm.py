"""Idempotent entity repair for the LayerNorm build, via RCON.

Ghost-revival lost 263/4439 entities (242 arithmetic-combinator, 18
decider-combinator, 3 substation -- constant-combinator, medium-electric-
pole and electric-energy-interface all built at 100%). This recreates any
entity of the three affected types that isn't present at its expected
real-world position, using the exact control_behavior config from the
decoded blueprint (draftsman's to_dict() shape matches the live
LuaControlBehavior.parameters shape directly -- verified by inspecting an
already-built decider-combinator over RCON, comparator is the literal
unicode symbol e.g. "≥", not an ASCII "vs`>=" alias).

Real-world offset (OX, OY) was measured empirically via the blueprint's
single electric-energy-interface (local (1989.5, 0.5) -> real (-438,
-299)), per this project's standing rule: measure live, don't compute the
local->world offset analytically.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_layernorm_full_test_blueprint.txt")
OX, OY = -2427.5, -299.5
AFFECTED_TYPES = {"arithmetic-combinator", "decider-combinator", "substation"}

bp_string = open(BLUEPRINT_PATH, encoding="utf-8").read().strip()
bp = get_blueprintable_from_string(bp_string)

manifest = []
for e in bp.entities:
    if e.name not in AFFECTED_TYPES:
        continue
    d = e.to_dict()
    item = {"name": e.name, "x": d["position"]["x"] + OX, "y": d["position"]["y"] + OY}
    if "quality" in d:
        item["quality"] = d["quality"]
    if "control_behavior" in d:
        item["control_behavior"] = d["control_behavior"]
    manifest.append(item)

print(f"manifest entries: {len(manifest)}")
manifest_json = json.dumps(manifest)
print(f"manifest JSON size: {len(manifest_json)} bytes")

lua = f'''
local surf = game.surfaces["nauvis"]
local force = game.forces["player"]
local manifest = helpers.json_to_table("__MANIFEST__")
local created, skipped, errors = 0, 0, 0
local first_error = nil
for _, item in pairs(manifest) do
  local existing = surf.find_entities_filtered{{name=item.name, area={{{{item.x-0.4, item.y-0.4}}, {{item.x+0.4, item.y+0.4}}}}, limit=1}}
  if #existing == 0 then
    local ok, err = pcall(function()
      local params = {{name=item.name, position={{item.x, item.y}}, force=force, raise_built=false}}
      if item.quality then params.quality = item.quality end
      local ent = surf.create_entity(params)
      if not ent then error("create_entity returned nil") end
      if item.control_behavior then
        if item.control_behavior.arithmetic_conditions then
          ent.get_or_create_control_behavior().parameters = item.control_behavior.arithmetic_conditions
        elseif item.control_behavior.decider_conditions then
          ent.get_or_create_control_behavior().parameters = item.control_behavior.decider_conditions
        end
      end
    end)
    if ok then
      created = created + 1
    else
      errors = errors + 1
      if not first_error then first_error = tostring(err) end
    end
  else
    skipped = skipped + 1
  end
end
helpers.write_file("repair.json", helpers.table_to_json({{created=created, skipped=skipped, errors=errors, first_error=first_error}}), false)
rcon.print("created=" .. created .. " skipped=" .. skipped .. " errors=" .. errors .. " first_error=" .. tostring(first_error))
'''.strip()

lua = lua.replace("__MANIFEST__", manifest_json.replace("\\", "\\\\").replace('"', '\\"'))

with open(os.path.join(os.path.dirname(__file__), "rcon_repair_layernorm_cmd.txt"), "w", encoding="utf-8") as f:
    f.write("/c " + lua)
print(f"lua command size: {len(lua)} bytes")

with connect(timeout=60.0) as c:
    resp = c.command("/c " + lua)
    sys.stdout.buffer.write(resp.strip().encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
