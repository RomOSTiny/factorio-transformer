OX, OY = 423.0, 290.0

# t_ctr local (0.5, 1.0)
tctr_x, tctr_y = 0.5 + OX, 1.0 + OY
# gate_0/acc_0/out_0 local x = ACC_X+0*SLOT_W + {0.5,2.5,4.5}, y = ACC_Y+1.0
# ACC_X=ALU_X=150, ACC_Y=420 -> local (150.5,421),(152.5,421),(154.5,421)
g0x, g0y = 150.5 + OX, 421.0 + OY
a0x, a0y = 152.5 + OX, 421.0 + OY
o0x, o0y = 154.5 + OX, 421.0 + OY
# also probe gate_11 (last slot): ACC_X+11*8=150+88=238 -> (238.5,421)
g11x, g11y = 238.5 + OX, 421.0 + OY

cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'local function dump(x,y,typ,label) '
    'local f=surf.find_entities_filtered{type=typ, area={{x-0.7,y-0.7},{x+0.7,y+0.7}}}; '
    'if #f==0 then out[label]="NOTFOUND"; return end; '
    'local e=f[1]; '
    'local ok1,sin=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green) end); '
    'local ok2,sout=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local function fmt(sig) local r={}; if sig then for _,s in pairs(sig) do r[#r+1]=s.signal.name.."="..s.count end end return r end; '
    'out[label]={pos={e.position.x,e.position.y}, input=fmt(ok1 and sin), output=fmt(ok2 and sout)}; '
    'end; '
    'dump(' + str(tctr_x) + ',' + str(tctr_y) + ',"arithmetic-combinator","t_ctr"); '
    'dump(' + str(g0x) + ',' + str(g0y) + ',"decider-combinator","gate_0"); '
    'dump(' + str(a0x) + ',' + str(a0y) + ',"arithmetic-combinator","acc_0"); '
    'dump(' + str(o0x) + ',' + str(o0y) + ',"arithmetic-combinator","out_0"); '
    'dump(' + str(g11x) + ',' + str(g11y) + ',"decider-combinator","gate_11"); '
    'out.tick=game.tick; '
    'helpers.write_file("matmul_deep_diag.json", helpers.table_to_json(out), false)'
)
with open("matmul_deep_diag_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd), "bytes")
