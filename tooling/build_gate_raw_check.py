OX, OY = 423.0, 1690.0
tctr_x, tctr_y = 0.5 + OX, 1.0 + OY
g0x, g0y = 150.5 + OX, 421.0 + OY
g1x, g1y = 158.5 + OX, 421.0 + OY

cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'local function dump(x,y,typ,label) '
    'local f=surf.find_entities_filtered{type=typ, area={{x-0.7,y-0.7},{x+0.7,y+0.7}}}; '
    'if #f==0 then out[label]="NOTFOUND"; return end; '
    'local e=f[1]; '
    'local ok1,sin=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green) end); '
    'local function fmt(sig) local r={}; if sig then for _,s in pairs(sig) do r[#r+1]=s.signal.name.."="..s.count end end return r end; '
    'out[label]=fmt(ok1 and sin); '
    'end; '
    'dump(' + str(tctr_x) + ',' + str(tctr_y) + ',"arithmetic-combinator","t_ctr_in"); '
    'dump(' + str(g0x) + ',' + str(g0y) + ',"decider-combinator","gate_0_in"); '
    'dump(' + str(g1x) + ',' + str(g1y) + ',"decider-combinator","gate_1_in"); '
    'out.tick=game.tick; '
    'helpers.write_file("gate_raw_check.json", helpers.table_to_json(out), false)'
)
with open("gate_raw_check_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
