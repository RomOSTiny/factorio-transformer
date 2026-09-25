BX, BY = 500, 700
area = "{{" + str(BX - 30) + "," + str(BY - 30) + "},{" + str(BX + 30) + "," + str(BY + 30) + "}}"
cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'local all={}; for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do '
    'local ok,net=pcall(function() return e.electric_network_id end); '
    'table.insert(all, {name=e.name, x=e.position.x, y=e.position.y, net=(ok and net) or "n/a"}) end; '
    'out.all=all; '
    'local o=nil; for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}) do '
    'local cb=e.get_control_behavior(); local p=(cb and cb.parameters); '
    'if p and p.first_signal and p.first_signal.name=="signal-I" and p.operation=="+" then o=e break end end; '
    'if o then local ok,sout=pcall(function() return o.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'out.o_collect_out={}; if ok and sout then for _,s in pairs(sout) do table.insert(out.o_collect_out,{name=s.signal.name,count=s.count}) end end '
    'out.o_collect_found=true; else out.o_collect_found=false end; '
    'helpers.write_file("octave_minimal_check3.json", helpers.table_to_json(out), false)'
)
with open("octave_minimal_check3_cmd.txt", "w") as f:
    f.write(cmd)
print("bytes:", len(cmd))
