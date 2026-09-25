"""Trim stray (non-manifest) wire connections in the exp0/exp1 addressed-ROM
area specifically. Root cause found live 07.09.2026: earlier cleanup
attempts only tried disconnect_from(target, defines.wire_origin.script),
but connections created by the ORIGINAL blueprint import/ghost-revival
process use defines.wire_origin.player instead - script-origin disconnect
silently no-ops on those (matches the already-documented "origin must
match connect_to's origin" gotcha, just for a second origin value nobody
had tried yet). This script tries BOTH origins for every disconnect.

Safety: bounded logic only (no while loops - see the 07.09.2026 hang
incident in factorio_known_gotchas.md), tight scope (ROM area bounding
box only, not the whole build), and signature+tolerance-based validity
check (not raw position-only) reusing the same pattern as
rcon_repair_wires_attention_v2.py.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

ARITH_OX, ARITH_OY = -2912.5, -273.0
CONST_OX, CONST_OY = -2913.0, -273.0
WIRED_TYPES = {"constant-combinator", "arithmetic-combinator", "decider-combinator"}

# exp0/exp1 ROM real-world bounding box (generous margin around both copies)
ROM_AREA = ((-920, 505), (-590, 810))

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_attention_full_test_blueprint.txt")
bp_string = open(BLUEPRINT_PATH, encoding="utf-8").read().strip()
bp = get_blueprintable_from_string(bp_string)
d = bp.to_dict()["blueprint"]
entities = d["entities"]
wires = d["wires"]


def real_pos(ent):
    lx, ly = ent["position"]["x"], ent["position"]["y"]
    if ent["name"] in ("arithmetic-combinator", "decider-combinator"):
        return lx + ARITH_OX, ly + ARITH_OY
    return lx + CONST_OX, ly + CONST_OY


valid_edges = []  # [x1,y1,c1,x2,y2,c2]
for e1n, c1, e2n, c2 in wires:
    ent1, ent2 = entities[e1n - 1], entities[e2n - 1]
    if ent1["name"] not in WIRED_TYPES or ent2["name"] not in WIRED_TYPES:
        continue
    x1, y1 = real_pos(ent1)
    x2, y2 = real_pos(ent2)
    valid_edges.append([round(x1, 3), round(y1, 3), c1, round(x2, 3), round(y2, 3), c2])

print(f"valid edges (whole blueprint): {len(valid_edges)}")
valid_json = json.dumps(valid_edges)

lua = '''
local surf = game.surfaces["nauvis"]
local VALID = helpers.json_to_table("__VALID__")
local AREA = {{__AX0__,__AY0__},{__AX1__,__AY1__}}
local TOL = 1.0

local function edge_is_valid(x1,y1,c1,x2,y2,c2)
  for _, v in pairs(VALID) do
    if v[3]==c1 and v[6]==c2 and math.abs(v[1]-x1)<TOL and math.abs(v[2]-y1)<TOL and math.abs(v[4]-x2)<TOL and math.abs(v[5]-y2)<TOL then
      return true
    end
    if v[3]==c2 and v[6]==c1 and math.abs(v[1]-x2)<TOL and math.abs(v[2]-y2)<TOL and math.abs(v[4]-x1)<TOL and math.abs(v[5]-y1)<TOL then
      return true
    end
  end
  return false
end

local ids = {defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green, defines.wire_connector_id.circuit_red, defines.wire_connector_id.circuit_green}

-- collect all live (entity,cid,target) tuples first (bounded, no while loop)
local all_conns = {}
for _, name in pairs({"constant-combinator", "arithmetic-combinator", "decider-combinator"}) do
  for _, e in pairs(surf.find_entities_filtered{name=name, area=AREA}) do
    for _, cid in pairs(ids) do
      local ok, con = pcall(function() return e.get_wire_connector(cid, false) end)
      if ok and con then
        for _, c in pairs(con.connections) do
          local t = c.target
          if t and t.owner and t.owner.valid then
            table.insert(all_conns, {e=e, cid=cid, con=con, t=t})
          end
        end
      end
    end
  end
end

local checked, removed, failed = 0, 0, 0
for _, rec in pairs(all_conns) do
  checked = checked + 1
  local e, cid, con, t = rec.e, rec.cid, rec.con, rec.t
  if e.valid and t.owner.valid then
    if not edge_is_valid(e.position.x, e.position.y, cid, t.owner.position.x, t.owner.position.y, t.wire_connector_id) then
      -- try BOTH origins once each (bounded, no loop) - the actual fix
      -- for the 07.09.2026 finding that blueprint-import connections use
      -- player origin, not script
      local ok1 = pcall(function() con.disconnect_from(t, defines.wire_origin.script) end)
      local ok2 = pcall(function() con.disconnect_from(t, defines.wire_origin.player) end)
      if ok1 or ok2 then removed = removed + 1 else failed = failed + 1 end
    end
  end
end
rcon.print("checked=" .. checked .. " removed=" .. removed .. " failed=" .. failed)
'''.strip()

lua = lua.replace("__VALID__", valid_json.replace("\\", "\\\\").replace('"', '\\"'))
lua = lua.replace("__AX0__", str(ROM_AREA[0][0])).replace("__AY0__", str(ROM_AREA[0][1]))
lua = lua.replace("__AX1__", str(ROM_AREA[1][0])).replace("__AY1__", str(ROM_AREA[1][1]))
print(f"lua size: {len(lua)}")

with connect(timeout=180.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
