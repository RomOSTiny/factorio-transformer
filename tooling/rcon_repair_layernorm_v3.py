"""Clean entity repair for the re-built (bugfixed) LayerNorm schema.

Uses the now-confirmed correct offset for every type except EEI:
OX,OY = -2428.0,-300.0 (base EEI-derived offset -2427.5,-299.5, minus the
universal -0.5,-0.5 shift discovered during the previous debugging
session). With the right offset from the start, a simple tight-tolerance
existence check is sufficient -- no need for the signature+wide-radius
greedy matching the previous (wrong-offset) attempt required.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

OX, OY = -2428.0, -300.0
AFFECTED_TYPES = {"arithmetic-combinator", "decider-combinator", "substation"}

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_layernorm_full_test_blueprint.txt")
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

lua = '''
local surf = game.surfaces["nauvis"]
local force = game.forces["player"]
local manifest = helpers.json_to_table("__MANIFEST__")
local created, skipped, errors = 0, 0, 0
for _, item in pairs(manifest) do
  local existing = surf.find_entities_filtered{name=item.name, area={{item.x-0.2, item.y-0.2}, {item.x+0.2, item.y+0.2}}, limit=1}
  if #existing == 0 then
    local ok = pcall(function()
      local params = {name=item.name, position={item.x, item.y}, force=force, raise_built=false}
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
    if ok then created = created + 1 else errors = errors + 1 end
  else
    skipped = skipped + 1
  end
end
rcon.print("created=" .. created .. " skipped=" .. skipped .. " errors=" .. errors)
'''.strip()

lua = lua.replace("__MANIFEST__", manifest_json.replace("\\", "\\\\").replace('"', '\\"'))

with connect(timeout=90.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
