OX, OY = 1223.0, 290.0
tctr_x, tctr_y = 0.5 + OX, 1.0 + OY
a5x, a5y = 192.5 + OX, 421.0 + OY
o5x, o5y = 194.5 + OX, 421.0 + OY

cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'local function dump(x,y,typ,label) '
    'local f=surf.find_entities_filtered{type=typ, area={{x-0.7,y-0.7},{x+0.7,y+0.7}}}; '
    'if #f==0 then out[label]="NOTFOUND"; return end; '
    'local e=f[1]; '
    'local ok,sig=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local function fmt(sig) local r={}; if sig then for _,s in pairs(sig) do r[#r+1]=s.signal.name.."="..s.count end end return r end; '
    'out[label]={pos={e.position.x,e.position.y}, unit=e.unit_number, output=fmt(ok and sig)}; '
    'end; '
    'dump(' + str(tctr_x) + ',' + str(tctr_y) + ',"arithmetic-combinator","t_ctr"); '
    'dump(' + str(a5x) + ',' + str(a5y) + ',"arithmetic-combinator","acc_5"); '
    'dump(' + str(o5x) + ',' + str(o5y) + ',"arithmetic-combinator","out_5"); '
    'out.tick=game.tick; out.surface=surf.name; out.pos_check=game.player.position; '
    'helpers.write_file("direct_recheck.json", helpers.table_to_json(out), false)'
)
with open("direct_recheck_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
