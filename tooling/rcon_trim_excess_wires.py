"""Systematic fix for the duplicate-relay-chain doubling bug found live
06.09.2026: entity-repair's signature+0.6-tolerance match for the 17
missing arithmetic-combinators apparently created duplicate parallel
gbridge_N relay chains in several places (each an independent computing
source that re-broadcasts the same values, so two parallel chains into
one consumer literally sums them = doubling), on top of drifted originals
that were never actually missing.

Fix: for each entity+connector, count how many connections the manifest
says it should have (from the SOURCE blueprint's `wires` list) vs how
many it actually has live. If actual > expected, remove excess
connections - prefer keeping the connections that correspond exactly to
a signature-verified manifest edge (same approach as v2 wire-repair),
disconnecting the rest via disconnect_from(target, wire_origin.script)
(the origin argument is REQUIRED or disconnect silently no-ops, found
live earlier this session).
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


# expected_count[(name,round(x,1),round(y,1),cid)] = how many manifest
# edges touch this specific port
from collections import defaultdict
expected_count = defaultdict(int)
edge_list = []  # (name1,x1,y1,c1,name2,x2,y2,c2)
for e1n, c1, e2n, c2 in wires:
    ent1, ent2 = entities[e1n - 1], entities[e2n - 1]
    if ent1["name"] not in WIRED_TYPES or ent2["name"] not in WIRED_TYPES:
        continue
    x1, y1 = real_pos(ent1)
    x2, y2 = real_pos(ent2)
    k1 = (ent1["name"], round(x1, 1), round(y1, 1), c1)
    k2 = (ent2["name"], round(x2, 1), round(y2, 1), c2)
    expected_count[k1] += 1
    expected_count[k2] += 1
    edge_list.append([ent1["name"], round(x1, 3), round(y1, 3), c1, ent2["name"], round(x2, 3), round(y2, 3), c2])

print(f"distinct ports with expected edges: {len(expected_count)}")
expected_json = json.dumps([[k[0], k[1], k[2], k[3], v] for k, v in expected_count.items()])
edges_json = json.dumps(edge_list)
print(f"expected size: {len(expected_json)}, edges size: {len(edges_json)}")

lua = '''
local surf = game.surfaces["nauvis"]
local EXPECTED = helpers.json_to_table("__EXPECTED__")
local EDGES = helpers.json_to_table("__EDGES__")

local exp_map = {}
for _, e in pairs(EXPECTED) do
  local key = e[1] .. "|" .. string.format("%.1f", e[2]) .. "|" .. string.format("%.1f", e[3]) .. "|" .. e[4]
  exp_map[key] = e[5]
end

-- for a given entity+cid, find which live target units correspond to a
-- valid manifest edge (within tolerance), preferring those matches
local function valid_targets_for(name, x, y, cid)
  local matches = {}
  for _, ed in pairs(EDGES) do
    local n1,x1,y1,c1,n2,x2,y2,c2 = ed[1],ed[2],ed[3],ed[4],ed[5],ed[6],ed[7],ed[8]
    if n1==name and c1==cid and math.abs(x1-x)<1.5 and math.abs(y1-y)<1.5 then
      table.insert(matches, {n2,x2,y2,c2})
    elseif n2==name and c2==cid and math.abs(x2-x)<1.5 and math.abs(y2-y)<1.5 then
      table.insert(matches, {n1,x1,y1,c1})
    end
  end
  return matches
end

local ids = {defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green, defines.wire_connector_id.circuit_red, defines.wire_connector_id.circuit_green}

local trimmed, checked_ports = 0, 0
for _, name in pairs({"constant-combinator", "arithmetic-combinator", "decider-combinator"}) do
  for _, e in pairs(surf.find_entities_filtered{name=name, area={{-1100,-500},{-500,1300}}}) do
    for _, cid in pairs(ids) do
      local ok, con = pcall(function() return e.get_wire_connector(cid, false) end)
      if ok and con and #con.connections > 0 then
        local key = name .. "|" .. string.format("%.1f", e.position.x) .. "|" .. string.format("%.1f", e.position.y) .. "|" .. cid
        local expect = exp_map[key] or 0
        local actual = #con.connections
        checked_ports = checked_ports + 1
        if actual > expect and expect >= 0 then
          -- find valid target descriptors for this port
          local valid = valid_targets_for(name, e.position.x, e.position.y, cid)
          local kept = 0
          local to_remove = {}
          for _, c in pairs(con.connections) do
            local t = c.target
            if t and t.owner and t.owner.valid then
              local is_valid = false
              for _, v in pairs(valid) do
                if t.owner.name==v[1] and t.wire_connector_id==v[4] and math.abs(t.owner.position.x-v[2])<1.5 and math.abs(t.owner.position.y-v[3])<1.5 then
                  is_valid = true
                  break
                end
              end
              if is_valid and kept < expect then
                kept = kept + 1
              else
                table.insert(to_remove, t)
              end
            end
          end
          for _, t in pairs(to_remove) do
            local ok2 = pcall(function() con.disconnect_from(t, defines.wire_origin.script) end)
            if ok2 then trimmed = trimmed + 1 end
          end
        end
      end
    end
  end
end
rcon.print("checked_ports=" .. checked_ports .. " trimmed=" .. trimmed)
'''.strip()

lua = lua.replace("__EXPECTED__", expected_json.replace("\\", "\\\\").replace('"', '\\"'))
lua = lua.replace("__EDGES__", edges_json.replace("\\", "\\\\").replace('"', '\\"'))
print(f"lua size: {len(lua)}")

with connect(timeout=280.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
