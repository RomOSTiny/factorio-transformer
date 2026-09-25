OX, OY = 423.0, 990.0
a0x, a0y = 152.5 + OX, 421.0 + OY  # acc_0
o0x, o0y = 154.5 + OX, 421.0 + OY  # out_0

cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'local function probe(x,y,label) '
    'local f=surf.find_entities_filtered{type="arithmetic-combinator", area={{x-0.7,y-0.7},{x+0.7,y+0.7}}}; '
    'if #f==0 then out[label]="NOTFOUND"; return end; '
    'local e=f[1]; local rec={pos={e.position.x,e.position.y}, unit=e.unit_number}; '
    'for _,cn in pairs({"combinator_input_red","combinator_input_green","combinator_output_red","combinator_output_green"}) do '
    'local ok,wc=pcall(function() return e.get_wire_connector(defines.wire_connector_id[cn], false) end); '
    'rec[cn]=(ok and wc) and wc.real_connection_count or "N/A" end; '
    'out[label]=rec end; '
    'probe(' + str(a0x) + ',' + str(a0y) + ',"acc_0"); '
    'probe(' + str(o0x) + ',' + str(o0y) + ',"out_0"); '
    'helpers.write_file("port_check.json", helpers.table_to_json(out), false)'
)
with open("port_check_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
