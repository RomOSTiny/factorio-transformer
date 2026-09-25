"""Cleanup v2: fixes the v1 cleanup bug (string-formatted key comparison
was sensitive to Python-vs-Lua float rounding at the 0.1 boundary,
apparently causing near-universal false negatives). This version compares
with a numeric tolerance directly in Lua instead."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

ARITH_OX, ARITH_OY = -2912.5, -273.0
CONST_OX, CONST_OY = -2913.0, -273.0
WIRED_TYPES = {"constant-combinator", "arithmetic-combinator", "decider-combinator"}

bp_string = open(os.path.join(os.path.dirname(__file__), "stage2_attention_full_test_blueprint.txt"), encoding="utf-8").read().strip()
bp = get_blueprintable_from_string(bp_string)
d = bp.to_dict()["blueprint"]
entities = d["entities"]
wires = d["wires"]


def real_pos(ent):
    lx, ly = ent["position"]["x"], ent["position"]["y"]
    if ent["name"] in ("arithmetic-combinator", "decider-combinator"):
        return lx + ARITH_OX, ly + ARITH_OY
    return lx + CONST_OX, ly + CONST_OY


valid_edges = []  # each entry: [x1,y1,c1,x2,y2,c2]
for e1n, c1, e2n, c2 in wires:
    ent1, ent2 = entities[e1n - 1], entities[e2n - 1]
    if ent1["name"] not in WIRED_TYPES or ent2["name"] not in WIRED_TYPES:
        continue
    x1, y1 = real_pos(ent1)
    x2, y2 = real_pos(ent2)
    valid_edges.append([round(x1, 3), round(y1, 3), c1, round(x2, 3), round(y2, 3), c2])

print(f"valid edges: {len(valid_edges)}")
valid_json = json.dumps(valid_edges)

lua = '''
local surf = game.surfaces["nauvis"]
local VALID = helpers.json_to_table("__VALID__")

local function edge_is_valid(x1,y1,c1,x2,y2,c2)
  for _, v in pairs(VALID) do
    if v[3]==c1 and v[6]==c2 and math.abs(v[1]-x1)<0.2 and math.abs(v[2]-y1)<0.2 and math.abs(v[4]-x2)<0.2 and math.abs(v[5]-y2)<0.2 then
      return true
    end
    if v[3]==c2 and v[6]==c1 and math.abs(v[1]-x2)<0.2 and math.abs(v[2]-y2)<0.2 and math.abs(v[4]-x1)<0.2 and math.abs(v[5]-y1)<0.2 then
      return true
    end
  end
  return false
end

local ids = {defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green, defines.wire_connector_id.circuit_red, defines.wire_connector_id.circuit_green}

-- collect ALL (entity,cid,target,target_cid) tuples first (both sides will
-- each report the same physical wire once from their own perspective) to
-- avoid mutating while iterating
local all_conns = {}
for _, name in pairs({"constant-combinator", "arithmetic-combinator", "decider-combinator"}) do
  for _, e in pairs(surf.find_entities_filtered{name=name, area={{-1100,-500},{-500,1300}}}) do
    for _, cid in pairs(ids) do
      local ok, con = pcall(function() return e.get_wire_connector(cid, false) end)
      if ok and con then
        for _, c in pairs(con.connections) do
          local t = c.target
          if t and t.owner and t.owner.valid then
            table.insert(all_conns, {e=e, cid=cid, t=t})
          end
        end
      end
    end
  end
end

local checked, removed = 0, 0
for _, rec in pairs(all_conns) do
  checked = checked + 1
  local e, cid, t = rec.e, rec.cid, rec.t
  if e.valid and t.owner.valid then
    if not edge_is_valid(e.position.x, e.position.y, cid, t.owner.position.x, t.owner.position.y, t.wire_connector_id) then
      local ok, con = pcall(function() return e.get_wire_connector(cid, false) end)
      if ok and con then
        local ok2 = pcall(function() con.disconnect_from(t, defines.wire_origin.script) end)
        if ok2 then removed = removed + 1 end
      end
    end
  end
end
rcon.print("checked=" .. checked .. " removed=" .. removed)
'''.strip()

lua = lua.replace("__VALID__", valid_json.replace("\\", "\\\\").replace('"', '\\"'))
print(f"lua size: {len(lua)}")

with connect(timeout=180.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
