"""Idempotent wire repair, generalized from this session's repair_ln_wires.py.
Resolves every blueprint `wires` entry to world endpoints, finds each
endpoint by name + nearest live within 1.6 tiles, and adds the edge only
if not already present.
"""
import json, sys
sys.path.insert(0, r"C:\Users\roma_\Desktop\factorio-ai\tooling")
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

bp_path = sys.argv[1]
OX, OY = float(sys.argv[2]), float(sys.argv[3])
CX, CY, HX, HY = float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6]), float(sys.argv[7])

WIRED = {"arithmetic-combinator", "decider-combinator", "constant-combinator"}
bp = get_blueprintable_from_string(open(bp_path, encoding="utf-8").read().strip())
d = bp.to_dict()["blueprint"]
ents, wires = d["entities"], d.get("wires", [])

wm = []
for e1n, c1, e2n, c2 in wires:
    a, b = ents[e1n - 1], ents[e2n - 1]
    if a["name"] not in WIRED or b["name"] not in WIRED:
        continue
    wm.append([a["name"], round(a["position"]["x"] + OX, 3), round(a["position"]["y"] + OY, 3), c1,
               b["name"], round(b["position"]["x"] + OX, 3), round(b["position"]["y"] + OY, 3), c2])
print(f"wire manifest: {len(wm)} of {len(wires)} total")
payload = json.dumps(wm)

lua = r'''
local surf = game.surfaces["nauvis"]
local W = helpers.json_to_table("__PAYLOAD__")
local area = {{__CX__-__HX__,__CY__-__HY__},{__CX__+__HX__,__CY__+__HY__}}
local buckets = {}
local function bk(x,y) return math.floor(x/3) .. "," .. math.floor(y/3) end
for _, nm in pairs({"arithmetic-combinator","decider-combinator","constant-combinator"}) do
  for _, e in pairs(surf.find_entities_filtered{area=area, name=nm}) do
    local k = bk(e.position.x, e.position.y)
    buckets[k] = buckets[k] or {}
    table.insert(buckets[k], e)
  end
end
local function find_near(name, x, y)
  local bx, by = math.floor(x/3), math.floor(y/3)
  local best, bd = nil, 1e9
  for dx=-1,1 do for dy=-1,1 do
    local lst = buckets[(bx+dx)..","..(by+dy)]
    if lst then for _, e in pairs(lst) do
      if e.valid and e.name == name then
        local ddx, ddy = e.position.x-x, e.position.y-y
        local dd = ddx*ddx+ddy*ddy
        if dd < bd then bd = dd; best = e end
      end
    end end
  end end
  if best and bd <= 2.56 then return best end
  return nil
end
local function has_edge(con, unit, cid)
  local ok, cs = pcall(function() return con.connections end)
  if not ok or not cs then return nil end
  for _, cn in pairs(cs) do
    local t = cn.target
    if t and t.owner and t.owner.valid and t.owner.unit_number == unit and t.wire_connector_id == cid then return true end
  end
  return false
end
local connected, already, missing_ep, failed = 0, 0, 0, 0
for i = 1, #W do
  local w = W[i]
  local e1 = find_near(w[1], w[2], w[3])
  local e2 = find_near(w[5], w[6], w[7])
  if not e1 or not e2 then missing_ep = missing_ep + 1
  else
    local ok = pcall(function()
      local c1 = e1.get_wire_connector(w[4], true)
      local c2 = e2.get_wire_connector(w[8], true)
      local ex = has_edge(c1, e2.unit_number, w[8])
      if ex == true then already = already + 1
      elseif ex == false then c1.connect_to(c2, false, defines.wire_origin.script); connected = connected + 1
      else
        if c1.real_connection_count == 0 or c2.real_connection_count == 0 then
          c1.connect_to(c2, false, defines.wire_origin.script); connected = connected + 1
        else already = already + 1 end
      end
    end)
    if not ok then failed = failed + 1 end
  end
end
local res = {connected=connected, already=already, missing_endpoint=missing_ep, failed=failed, wires_total=#W, tick=game.tick}
rcon.print(helpers.table_to_json(res))
'''.replace("__PAYLOAD__", payload.replace("\\", "\\\\").replace('"', '\\"')).replace("__CX__", str(CX)).replace("__CY__", str(CY)).replace("__HX__", str(HX)).replace("__HY__", str(HY))

print(f"lua size {len(lua)}")
with connect(timeout=240) as c:
    print(c.command("/c " + lua))
