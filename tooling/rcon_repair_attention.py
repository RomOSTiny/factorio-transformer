"""Idempotent repair for the Attention build: 15 missing arithmetic-
combinator + 2 missing substation (out of 4099 revived, matching the
17-failure count exactly). Offsets measured live (not computed
analytically, per this project's standing rule):
  constant-combinator (and decider/substation, unverified but assumed same
  family): OX,OY = -2913.0, -273.0 (from c_Q1_0: local (2000.5,0.5) -> real
  (-912.5,-272.5))
  arithmetic-combinator: OX,OY = -2912.5, -273.0 (+0.5 in X only vs the
  constant-combinator offset - confirmed on d0_term_0 AND d0_term_1, a
  different quirk pattern than LayerNorm's -0.5,-0.5-for-everything).
"""
import json
import sys

sys.path.insert(0, "tooling")
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

CONST_OX, CONST_OY = -2913.0, -273.0
ARITH_OX, ARITH_OY = -2912.5, -273.0

bp_string = open("tooling/stage2_attention_full_test_blueprint.txt", encoding="utf-8").read().strip()
bp = get_blueprintable_from_string(bp_string)

expected_arith = []
expected_sub = []
for e in bp.entities:
    if e.name == "arithmetic-combinator":
        d = e.to_dict()["control_behavior"]["arithmetic_conditions"]
        expected_arith.append({"x": e.position.x + ARITH_OX, "y": e.position.y + ARITH_OY, "cb": d})
    elif e.name == "substation":
        expected_sub.append({"x": e.position.x + CONST_OX, "y": e.position.y + CONST_OY})

print(f"expected arithmetic-combinator: {len(expected_arith)}, substation: {len(expected_sub)}")

manifest = {"arith": expected_arith, "sub": expected_sub}
manifest_json = json.dumps(manifest)
print(f"manifest size: {len(manifest_json)} bytes")

lua = '''
local surf = game.surfaces["nauvis"]
local force = game.forces["player"]
local M = helpers.json_to_table("__MANIFEST__")

local created_a, skipped_a, failed_a = 0, 0, 0
for _, item in pairs(M.arith) do
  local found = surf.find_entities_filtered{name="arithmetic-combinator", area={{item.x-0.6,item.y-0.6},{item.x+0.6,item.y+0.6}}, limit=1}
  if #found == 0 then
    local ok = pcall(function()
      local ent = surf.create_entity{name="arithmetic-combinator", position={item.x, item.y}, force=force, raise_built=false}
      if not ent then error("nil entity") end
      ent.get_or_create_control_behavior().parameters = item.cb
    end)
    if ok then created_a = created_a + 1 else failed_a = failed_a + 1 end
  else
    skipped_a = skipped_a + 1
  end
end

local created_s, skipped_s, failed_s = 0, 0, 0
for _, item in pairs(M.sub) do
  local found = surf.find_entities_filtered{name="substation", area={{item.x-0.6,item.y-0.6},{item.x+0.6,item.y+0.6}}, limit=1}
  if #found == 0 then
    local ok = pcall(function()
      local ent = surf.create_entity{name="substation", position={item.x, item.y}, force=force, quality="legendary", raise_built=false}
      if not ent then error("nil entity") end
    end)
    if ok then created_s = created_s + 1 else failed_s = failed_s + 1 end
  else
    skipped_s = skipped_s + 1
  end
end

rcon.print("arith created=" .. created_a .. " skipped=" .. skipped_a .. " failed=" .. failed_a .. " || sub created=" .. created_s .. " skipped=" .. skipped_s .. " failed=" .. failed_s)
'''.strip()

lua = lua.replace("__MANIFEST__", manifest_json.replace("\\", "\\\\").replace('"', '\\"'))

with connect(timeout=90.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
