"""Entity repair, generalized from this session's repair_ln_entities.py.
Greedy 1:1 nearest-match with config-signature check for arithmetic
combinators (dense ROM areas can have multiple close together with
different roles - position alone is not enough per CLAUDE.md gotchas).
Anything unmatched within 2.5 tiles gets created fresh with the same
control_behavior.
"""
import json, sys
sys.path.insert(0, r"C:\Users\roma_\Desktop\factorio-ai\tooling")
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

bp_path = sys.argv[1]
OX, OY = float(sys.argv[2]), float(sys.argv[3])
CX, CY, HX, HY = float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6]), float(sys.argv[7])

bp = get_blueprintable_from_string(open(bp_path, encoding="utf-8").read().strip())
d = bp.to_dict()["blueprint"]
ents = d["entities"]

WANT = {"arithmetic-combinator", "decider-combinator", "constant-combinator", "substation", "medium-electric-pole", "electric-energy-interface"}
manifest = []
for e in ents:
    nm = e["name"]
    if nm not in WANT:
        continue
    item = {"name": nm, "x": round(e["position"]["x"] + OX, 3), "y": round(e["position"]["y"] + OY, 3)}
    cb = e.get("control_behavior")
    if cb:
        item["cb"] = cb
    if "quality" in e:
        item["quality"] = e["quality"]
    manifest.append(item)

print(f"manifest: {len(manifest)} entities")
payload = json.dumps(manifest)

lua_template = '''
local surf = game.surfaces["nauvis"]
local force = game.forces["player"]
local M = helpers.json_to_table("__PAYLOAD__")
local area = {{__CX__-__HX__,__CY__-__HY__},{__CX__+__HX__,__CY__+__HY__}}

local buckets = {}
local function bk(x,y) return math.floor(x/4) .. "," .. math.floor(y/4) end
for _, nm in pairs({"arithmetic-combinator","decider-combinator","constant-combinator","substation","medium-electric-pole","electric-energy-interface"}) do
  for _, e in pairs(surf.find_entities_filtered{area=area, name=nm}) do
    local k = bk(e.position.x, e.position.y)
    buckets[k] = buckets[k] or {}
    table.insert(buckets[k], {e=e, claimed=false})
  end
end

local function ac_sig(e)
  local ok, p = pcall(function() return e.get_control_behavior().parameters end)
  if not ok or not p then return "?" end
  local fs = p.first_signal and p.first_signal.name or ("k" .. tostring(p.first_constant))
  local ss = p.second_signal and p.second_signal.name or ("k" .. tostring(p.second_constant))
  local os = p.output_signal and p.output_signal.name or "?"
  return (p.operation or "?") .. "|" .. fs .. "|" .. ss .. "|" .. os
end
local function want_ac_sig(cb)
  local a = cb and cb.arithmetic_conditions
  if not a then return "?" end
  local fs = a.first_signal and a.first_signal.name or ("k" .. tostring(a.first_constant or 0))
  local ss = a.second_signal and a.second_signal.name or ("k" .. tostring(a.second_constant or 0))
  local os = a.output_signal and a.output_signal.name or "?"
  return (a.operation or "*") .. "|" .. fs .. "|" .. ss .. "|" .. os
end

local created, matched, failed = 0, 0, 0
local by_type_created = {}
for _, it in pairs(M) do
  local best, bestd = nil, 1e9
  local bx, by = math.floor(it.x/4), math.floor(it.y/4)
  for dx=-1,1 do for dy=-1,1 do
    local lst = buckets[(bx+dx)..","..(by+dy)]
    if lst then for _, cand in pairs(lst) do
      if not cand.claimed and cand.e.valid and cand.e.name == it.name then
        local ddx, ddy = cand.e.position.x - it.x, cand.e.position.y - it.y
        local dd = ddx*ddx + ddy*ddy
        if dd < bestd then
          local okmatch = true
          if it.name == "arithmetic-combinator" and it.cb then
            okmatch = (ac_sig(cand.e) == want_ac_sig(it.cb))
          end
          if okmatch then bestd = dd; best = cand end
        end
      end
    end end
  end end
  if best and bestd <= 6.25 then
    best.claimed = true; matched = matched + 1
  else
    local params = {name=it.name, position={it.x, it.y}, force=force, raise_built=false}
    if it.quality then params.quality = it.quality end
    if it.name == "electric-energy-interface" then params.buffer_size = 1000000000 end
    local ok, ent = pcall(function() return surf.create_entity(params) end)
    if ok and ent then
      created = created + 1
      by_type_created[it.name] = (by_type_created[it.name] or 0) + 1
      if it.cb then
        pcall(function()
          local b = ent.get_or_create_control_behavior()
          if it.cb.arithmetic_conditions then b.parameters = it.cb.arithmetic_conditions
          elseif it.cb.decider_conditions then b.parameters = {conditions=it.cb.decider_conditions.conditions, outputs=it.cb.decider_conditions.outputs}
          elseif it.cb.sections then
            local s = it.cb.sections.sections
            if s and s[1] and s[1].filters and s[1].filters[1] then
              local f = s[1].filters[1]
              b.get_section(1).set_slot(1, {value={type="virtual", name=f.name, quality="normal"}, min=f.count})
            end
          end
        end)
      end
      local k = bk(ent.position.x, ent.position.y)
      buckets[k] = buckets[k] or {}
      table.insert(buckets[k], {e=ent, claimed=true})
    else
      failed = failed + 1
    end
  end
end

local unclaimed = 0
for _, lst in pairs(buckets) do for _, cand in pairs(lst) do
  if not cand.claimed and cand.e.valid then unclaimed = unclaimed + 1 end
end end

local res = {matched=matched, created=created, created_by_type=by_type_created, failed=failed, unclaimed_live=unclaimed, tick=game.tick}
rcon.print(helpers.table_to_json(res))
'''
lua = lua_template.replace("__PAYLOAD__", payload.replace("\\", "\\\\").replace('"', '\\"'))
lua = lua.replace("__CX__", str(CX)).replace("__CY__", str(CY)).replace("__HX__", str(HX)).replace("__HY__", str(HY))

print(f"lua size {len(lua)}")
with connect(timeout=180) as c:
    print(c.command("/c " + lua.replace("\n", " ")))
