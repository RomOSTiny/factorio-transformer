"""Set the staggered START offsets of every block and (re)start the whole DAG.

One RCON call: for every block set the `-OFFSET` constant of its shift
combinators, destroy+recreate its free-running counters and zero its output
latches (with all wires preserved) - all in the SAME tick, i.e. an emulated
"revive" of the whole DAG. Usage: python dag_start.py [--dry]
"""
import json
import math
import sys

from dag_lib import LUA_LIB, block, lua

K, PULSE = 1000, 700

BLOCK_KIND = {
    "embed": ("elat_", ["e_tctr", "o_tctr"], ["e_sh", "o_sh"]),
    "ln_attn": ("h1lat_", ["ln_tctr", "ln_tctr2"], ["ln_sh", "ln_sh2"]),
    "ln_ffn": ("h1lat_", ["ln_tctr", "ln_tctr2"], ["ln_sh", "ln_sh2"]),
    "ln_final": ("h1lat_", ["ln_tctr", "ln_tctr2"], ["ln_sh", "ln_sh2"]),
    "qkv": ("olat_", ["e_tctr", "o_tctr"], ["e_sh", "o_sh"]),
    "proj": ("olat_", ["e_tctr", "o_tctr"], ["e_sh", "o_sh"]),
    "fc1": ("olat_", ["e_tctr", "o_tctr"], ["e_sh", "o_sh"]),
    "fc2": ("olat_", ["e_tctr", "o_tctr"], ["e_sh", "o_sh"]),
    "logits": ("olat_", ["e_tctr", "o_tctr"], ["e_sh", "o_sh"]),
    "res1": ("olat_", ["e_tctr", "o_tctr"], ["e_sh", "o_sh"]),
    "res2": ("olat_", ["e_tctr", "o_tctr"], ["e_sh", "o_sh"]),
    "attn": ("alat_", ["q_tctr", "m_tctr", "o_tctr"], ["q_sh", "m_sh", "o_sh"]),
}

# chain relay counts of the built links (printed by dag_links.py)
RELAYS = dict(L1a=523, L1b=565, L2=215, L3q=360, L3k=353, L3v=539, L4=608, L5=492, L6a=1103,
              L6b=153, L7=567, L8=181, L9=375, L10=1183, L11=803, L12=327)
D = {k: v + 30 for k, v in RELAYS.items()}


def up(x):
    return int(math.ceil(x / 100.0) * 100)


def offsets():
    o = {"embed": 0}
    o["ln_attn"] = up(o["embed"] + PULSE + D["L1a"] + 30)
    o["qkv"] = up(o["ln_attn"] + PULSE + D["L2"] + 30)
    static_arrival = o["qkv"] + K + PULSE + max(D["L3k"], D["L3v"])
    o["attn"] = up(max(o["qkv"] + PULSE + D["L3q"] + 30, static_arrival + 100))
    o["proj"] = up(o["attn"] + PULSE + D["L4"] + 30)
    o["res1"] = up(max(o["embed"] + PULSE + D["L1b"], o["proj"] + PULSE + D["L5"]) + 30)
    o["ln_ffn"] = up(o["res1"] + PULSE + D["L6a"] + 30)
    o["fc1"] = up(o["ln_ffn"] + PULSE + D["L7"] + 30)
    o["fc2"] = up(o["fc1"] + PULSE + D["L8"] + 30)
    o["res2"] = up(max(o["res1"] + PULSE + D["L6b"], o["fc2"] + PULSE + D["L9"]) + 30)
    o["ln_final"] = up(o["res2"] + PULSE + D["L10"] + 30)
    o["logits"] = up(o["ln_final"] + K + PULSE + D["L11"] + 50)
    return o


def build_lua_script(offs):
    items = []  # (kind, x, y, offset)
    for name, (latpref, tctrs, shs) in BLOCK_KIND.items():
        b = block(name)
        for sid in shs:
            x, y, _ = b["ids"][sid]
            items.append(("sh", x, y, offs[name]))
        for tid in tctrs:
            x, y, _ = b["ids"][tid]
            items.append(("rc", x, y, 0))
        for eid, (x, y, nm) in b["ids"].items():
            if eid.startswith(latpref) and nm == "arithmetic-combinator":
                items.append(("rc", x, y, 0))
    arr = ",".join(f"{{'{k}',{x},{y},{o}}}" for k, x, y, o in items)
    body = f'''
local items = {{{arr}}}
local function near(x, y, tol)
  local best, bd = nil, 1e9
  for _, e in pairs(S.find_entities_filtered{{area={{{{x-tol,y-tol}},{{x+tol,y+tol}}}}, name="arithmetic-combinator"}}) do
    local d = (e.position.x-x)^2 + (e.position.y-y)^2
    if d < bd then bd = d best = e end
  end
  return best
end
local CIDS = {{defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green}}
local function recreate(e)
  local un = e.unit_number
  local rec = {{}}
  for _, cid in ipairs(CIDS) do
    local c = e.get_wire_connector(cid, false)
    if c then
      for _, cn in pairs(c.connections) do
        local t = cn.target
        rec[#rec+1] = {{cid, t.owner, t.wire_connector_id, t.owner.unit_number == un}}
      end
    end
  end
  local params = e.get_control_behavior().parameters
  local pos = e.position
  e.destroy()
  local n = S.create_entity{{name="arithmetic-combinator", position=pos, force=F, direction=defines.direction.north, raise_built=false}}
  n.get_or_create_control_behavior().parameters = params
  for _, r in ipairs(rec) do
    local tgt = r[2]
    if r[4] then tgt = n end
    if tgt.valid then
      n.get_wire_connector(r[1], true).connect_to(tgt.get_wire_connector(r[3], true), false, defines.wire_origin.script)
    end
  end
  return n
end
local nsh, nrc, miss = 0, 0, {{}}
for _, it in ipairs(items) do
  local e = near(it[2], it[3], 1.2)
  if not e then
    miss[#miss+1] = it[1] .. "@" .. it[2] .. "," .. it[3]
  elseif it[1] == "sh" then
    local p = e.get_control_behavior().parameters
    p.second_constant = it[4]
    e.get_control_behavior().parameters = p
    nsh = nsh + 1
  end
end
if #miss == 0 then
  for _, it in ipairs(items) do
    if it[1] == "rc" then
      local e = near(it[2], it[3], 1.2)
      if e then recreate(e) nrc = nrc + 1 end
    end
  end
end
rcon.print(helpers.table_to_json({{sh=nsh, rc=nrc, miss=miss, tick=game.tick}}))
'''
    return LUA_LIB + "local ok_, err_ = pcall(function()\n" + body + "\nend)\nif not ok_ then rcon.print('ERR ' .. tostring(err_)) end\n", len(items)


if __name__ == "__main__":
    offs = offsets()
    print("offsets:", json.dumps(offs))
    s, n = build_lua_script(offs)
    print("items:", n, "lua chars:", len(s))
    if "--dry" not in sys.argv:
        print(lua(s, timeout=300))
