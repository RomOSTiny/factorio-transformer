"""Wire repair for the Attention build, same proven pattern as
rcon_repair_wires_layernorm.py."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

CONST_OX, CONST_OY = -2913.0, -273.0
ARITH_OX, ARITH_OY = -2912.5, -273.0
WIRED_TYPES = {"constant-combinator", "arithmetic-combinator", "decider-combinator"}

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_attention_full_test_blueprint.txt")
bp_string = open(BLUEPRINT_PATH, encoding="utf-8").read().strip()
bp = get_blueprintable_from_string(bp_string)
d = bp.to_dict()["blueprint"]
entities = d["entities"]
wires = d["wires"]


def real_pos(ent):
    lx, ly = ent["position"]["x"], ent["position"]["y"]
    # decider-combinator shares arithmetic-combinator's offset (both are
    # "combinator-family" dual-port entities) - confirmed live via max_ge,
    # NOT the constant-combinator offset as first assumed.
    if ent["name"] in ("arithmetic-combinator", "decider-combinator"):
        return lx + ARITH_OX, ly + ARITH_OY
    return lx + CONST_OX, ly + CONST_OY


wire_manifest = []
skipped = 0
for e1n, c1, e2n, c2 in wires:
    ent1 = entities[e1n - 1]
    ent2 = entities[e2n - 1]
    if ent1["name"] not in WIRED_TYPES or ent2["name"] not in WIRED_TYPES:
        skipped += 1
        continue
    x1, y1 = real_pos(ent1)
    x2, y2 = real_pos(ent2)
    wire_manifest.append([ent1["name"], round(x1, 3), round(y1, 3), c1, ent2["name"], round(x2, 3), round(y2, 3), c2])

print(f"wire manifest entries: {len(wire_manifest)} (skipped {skipped} touching non-circuit types)")
manifest_json = json.dumps(wire_manifest)
print(f"manifest JSON size: {len(manifest_json)} bytes")

lua = '''
local surf = game.surfaces["nauvis"]
local W = helpers.json_to_table("__MANIFEST__")

local buckets = {}
for _, name in pairs({"constant-combinator", "arithmetic-combinator", "decider-combinator"}) do
  for _, e in pairs(surf.find_entities_filtered{name=name, area={{-1100,-500},{-500,1300}}}) do
    local bk = math.floor(e.position.x) .. "," .. math.floor(e.position.y)
    buckets[bk] = buckets[bk] or {}
    table.insert(buckets[bk], e)
  end
end

local function find_near(name, x, y)
  local bx, by = math.floor(x), math.floor(y)
  for dx = -1, 1 do
    for dy = -1, 1 do
      local list = buckets[(bx+dx) .. "," .. (by+dy)]
      if list then
        for _, e in pairs(list) do
          if e.name == name and math.abs(e.position.x-x) < 1.5 and math.abs(e.position.y-y) < 1.5 then
            return e
          end
        end
      end
    end
  end
  return nil
end

local function has_edge(con1, target_unit, target_cid)
  local ok, conns = pcall(function() return con1.connections end)
  if not ok or not conns then return nil end
  for _, conn in pairs(conns) do
    local t = conn.target
    if t and t.owner and t.owner.valid and t.owner.unit_number == target_unit and t.wire_connector_id == target_cid then
      return true
    end
  end
  return false
end

local connected, already, missing, failed, fallback_used = 0, 0, 0, 0, 0
local missing_list = {}
for i = 1, #W do
  local w = W[i]
  local name1, x1, y1, c1, name2, x2, y2, c2 = w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8]
  local e1 = find_near(name1, x1, y1)
  local e2 = find_near(name2, x2, y2)
  if e1 == nil or e2 == nil then
    missing = missing + 1
    table.insert(missing_list, name1 .. "@" .. x1 .. "," .. y1 .. " <-> " .. name2 .. "@" .. x2 .. "," .. y2)
  else
    local ok = pcall(function()
      local con1 = e1.get_wire_connector(c1, true)
      local con2 = e2.get_wire_connector(c2, true)
      local exists = has_edge(con1, e2.unit_number, c2)
      if exists == nil then
        fallback_used = fallback_used + 1
        if con1.real_connection_count == 0 or con2.real_connection_count == 0 then
          con1.connect_to(con2, false, defines.wire_origin.script)
          connected = connected + 1
        else
          already = already + 1
        end
      elseif exists then
        already = already + 1
      else
        con1.connect_to(con2, false, defines.wire_origin.script)
        connected = connected + 1
      end
    end)
    if not ok then failed = failed + 1 end
  end
end
helpers.write_file("wire_repair_attention.json", helpers.table_to_json({connected=connected, already=already, missing=missing, failed=failed, fallback_used=fallback_used, missing_list=missing_list}), false)
rcon.print("connected=" .. connected .. " already=" .. already .. " missing=" .. missing .. " failed=" .. failed .. " fallback_used=" .. fallback_used)
'''.strip()

lua = lua.replace("__MANIFEST__", manifest_json.replace("\\", "\\\\").replace('"', '\\"'))
print(f"lua command size: {len(lua)} bytes")

with connect(timeout=120.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
