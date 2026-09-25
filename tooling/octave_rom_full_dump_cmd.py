BX, BY = 650, 700
area = "{{" + str(BX - 300) + "," + str(BY - 300) + "},{" + str(BX + 300) + "," + str(BY + 300) + "}}"
cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do '
    'local rec={type=e.type, x=e.position.x, y=e.position.y}; '
    'if e.type=="entity-ghost" then rec.gname=e.ghost_name; '
    'local ok,cb=pcall(function() return e.get_or_create_control_behavior() end); '
    'if ok and cb and cb.parameters then local p=cb.parameters; '
    'rec.op=p.operation; rec.o1=(p.first_signal and p.first_signal.name) or p.first_constant; '
    'rec.o2=p.second_constant or (p.second_signal and p.second_signal.name); '
    'rec.outsig=p.output_signal and p.output_signal.name end end; '
    'table.insert(out, rec) end; '
    'helpers.write_file("octave_rom_full_dump.json", helpers.table_to_json({n=#out, entities=out}), false)'
)
with open("octave_rom_full_dump_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
