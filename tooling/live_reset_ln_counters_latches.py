"""Reset a LayerNorm-param instance's free-running counters AND its output
latches SIMULTANEOUSLY (the critical lesson from this session's Attention
debugging: resetting only the counter without zeroing the latch leaves the
latch holding a stale/corrupted value captured during an earlier, possibly
under-powered sweep - looks like a logic bug but is actually leftover
history). Takes the instance's world offset (local -> world = local + off).
"""
import sys
sys.path.insert(0, r"C:\Users\roma_\Desktop\factorio-ai\tooling")
from rcon_client import connect

OX, OY = float(sys.argv[1]), float(sys.argv[2])

# local coordinates, identical for every build_layernorm instance (same blueprint geometry)
LN_TCTR = (1980.5, -12.0)
LN_TCTR2 = (2440.0, 688.0)
LN_SH = (1983.5, -12.0)
LN_SH2 = (2443.0, 688.0)
GATES_LATS = []
for p in range(2):
    for i in range(4):
        gx, gy = (2434.0 if p == 0 else 2437.0), 700.0 + i * 6
        lx, ly = gx, gy + 2.5
        GATES_LATS.append((gx, gy, lx, ly))


def w(pt):
    return (pt[0] + OX, pt[1] + OY)


lua = r'''
local surf = game.surfaces["nauvis"]
local force = game.forces["player"]

local function reset_tctr(wx, wy, shx, shy)
  local old = surf.find_entities_filtered{area={{wx-1.5,wy-1.5},{wx+1.5,wy+1.5}}, type="arithmetic-combinator", limit=1}[1]
  local pos = old and {old.position.x, old.position.y} or {wx, wy}
  if old then old.destroy() end
  local e = surf.create_entity{name="arithmetic-combinator", position=pos, force=force, direction=defines.direction.north, raise_built=false}
  e.get_or_create_control_behavior().parameters = {first_signal={type="virtual",name="signal-T"}, operation="+", second_constant=1, output_signal={type="virtual",name="signal-T"}}
  local o = e.get_wire_connector(defines.wire_connector_id.combinator_output_red, true)
  local i = e.get_wire_connector(defines.wire_connector_id.combinator_input_red, true)
  o.connect_to(i, false, defines.wire_origin.script)
  local sh = surf.find_entities_filtered{area={{shx-1.5,shy-1.5},{shx+1.5,shy+1.5}}, type="arithmetic-combinator", limit=1}[1]
  if sh then
    o.connect_to(sh.get_wire_connector(defines.wire_connector_id.combinator_input_red, true), false, defines.wire_origin.script)
    return "ok"
  end
  return "NO ln_sh FOUND"
end

local function reset_latch(gx, gy, lx, ly)
  local old = surf.find_entities_filtered{area={{lx-1.0,ly-1.0},{lx+1.0,ly+1.0}}, type="arithmetic-combinator", limit=1}[1]
  local pos = old and {old.position.x, old.position.y} or {lx, ly}
  if old then old.destroy() end
  local e = surf.create_entity{name="arithmetic-combinator", position=pos, force=force, direction=defines.direction.north, raise_built=false}
  e.get_or_create_control_behavior().parameters = {first_signal={type="virtual",name="signal-X"}, operation="+", second_signal={type="virtual",name="signal-Y"}, output_signal={type="virtual",name="signal-X"}}
  local o = e.get_wire_connector(defines.wire_connector_id.combinator_output_red, true)
  local i = e.get_wire_connector(defines.wire_connector_id.combinator_input_red, true)
  o.connect_to(i, false, defines.wire_origin.script)
  local gate = surf.find_entities_filtered{area={{gx-1.0,gy-1.0},{gx+1.0,gy+1.0}}, type="decider-combinator", limit=1}[1]
  if gate then
    gate.get_wire_connector(defines.wire_connector_id.combinator_output_red, true).connect_to(i, false, defines.wire_origin.script)
    return "ok"
  end
  return "NO gate FOUND"
end

local r1 = reset_tctr(__TCTR__, __SH__)
local r2 = reset_tctr(__TCTR2__, __SH2__)
local latch_results = {}
__LATCH_CALLS__

rcon.print(helpers.table_to_json({r1=r1, r2=r2, latches=latch_results, tick=game.tick}))
'''

tctr_w = w(LN_TCTR)
sh_w = w(LN_SH)
tctr2_w = w(LN_TCTR2)
sh2_w = w(LN_SH2)

latch_calls = []
for idx, (gx, gy, lx, ly) in enumerate(GATES_LATS):
    gxw, gyw = w((gx, gy))
    lxw, lyw = w((lx, ly))
    latch_calls.append(f'table.insert(latch_results, reset_latch({gxw},{gyw},{lxw},{lyw}))')

lua = lua.replace("__TCTR__", f"{tctr_w[0]},{tctr_w[1]}")
lua = lua.replace("__SH__", f"{sh_w[0]},{sh_w[1]}")
lua = lua.replace("__TCTR2__", f"{tctr2_w[0]},{tctr2_w[1]}")
lua = lua.replace("__SH2__", f"{sh2_w[0]},{sh2_w[1]}")
lua = lua.replace("__LATCH_CALLS__", "\n".join(latch_calls))

with connect(timeout=60) as c:
    print(c.command("/c " + lua.replace("\n", " ")))
