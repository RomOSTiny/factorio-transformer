"""Targeted cleanup: remove only connections that don't correspond to ANY
edge in the manifest (wrong-pair wires, like the p1_0<->p0_0 case found
live) -- leave duplicate correct-pair wires alone (harmless: two wires
between the same two points is still just one merged network, not a
signal doubling)."""
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


# valid_pairs: set of (round(x1,1),round(y1,1),c1, round(x2,1),round(y2,1),c2) in BOTH directions
valid_pairs = set()
for e1n, c1, e2n, c2 in wires:
    ent1, ent2 = entities[e1n - 1], entities[e2n - 1]
    if ent1["name"] not in WIRED_TYPES or ent2["name"] not in WIRED_TYPES:
        continue
    x1, y1 = real_pos(ent1)
    x2, y2 = real_pos(ent2)
    key1 = (round(x1, 1), round(y1, 1), c1, round(x2, 1), round(y2, 1), c2)
    key2 = (round(x2, 1), round(y2, 1), c2, round(x1, 1), round(y1, 1), c1)
    valid_pairs.add(key1)
    valid_pairs.add(key2)

print(f"valid directed pairs: {len(valid_pairs)}")
valid_json = json.dumps([list(k) for k in valid_pairs])
print(f"valid_json size: {len(valid_json)} bytes")

lua = '''
local surf = game.surfaces["nauvis"]
local VALID = helpers.json_to_table("__VALID__")
local valid_set = {}
for _, v in pairs(VALID) do
  local key = string.format("%.1f,%.1f,%d,%.1f,%.1f,%d", v[1], v[2], v[3], v[4], v[5], v[6])
  valid_set[key] = true
end

local ids = {defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green, defines.wire_connector_id.circuit_red, defines.wire_connector_id.circuit_green}

local checked, removed = 0, 0
local removed_list = {}
for _, name in pairs({"constant-combinator", "arithmetic-combinator", "decider-combinator"}) do
  for _, e in pairs(surf.find_entities_filtered{name=name, area={{-1100,-500},{-500,1300}}}) do
    for _, cid in pairs(ids) do
      local ok, con = pcall(function() return e.get_wire_connector(cid, false) end)
      if ok and con then
        local to_remove = {}
        for _, c in pairs(con.connections) do
          local t = c.target
          if t and t.owner and t.owner.valid then
            checked = checked + 1
            local key = string.format("%.1f,%.1f,%d,%.1f,%.1f,%d", e.position.x, e.position.y, cid, t.owner.position.x, t.owner.position.y, t.wire_connector_id)
            if not valid_set[key] then
              table.insert(to_remove, t)
              table.insert(removed_list, string.format("%s(%d)@%.1f,%.1f/%d -> %s(%d)@%.1f,%.1f/%d", e.name, e.unit_number, e.position.x, e.position.y, cid, t.owner.name, t.owner.unit_number, t.owner.position.x, t.owner.position.y, t.wire_connector_id))
            end
          end
        end
        for _, t in pairs(to_remove) do
          local ok2 = pcall(function() con.disconnect_from(t) end)
          if ok2 then removed = removed + 1 end
        end
      end
    end
  end
end
helpers.write_file("cleanup_wrong_wires.json", helpers.table_to_json({checked=checked, removed=removed, removed_list=removed_list}), false)
rcon.print("checked=" .. checked .. " removed=" .. removed)
'''.strip()

lua = lua.replace("__VALID__", valid_json.replace("\\", "\\\\").replace('"', '\\"'))

with connect(timeout=180.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
