BX, BY = 500, 500
area = "{{" + str(BX - 30) + "," + str(BY - 30) + "},{" + str(BX + 30) + "," + str(BY + 30) + "}}"
cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'local gen=surf.is_chunk_generated({x=' + str(BX // 32) + ',y=' + str(BY // 32) + '}); '
    'local all={}; for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do table.insert(all, {name=e.name, type=e.type, x=e.position.x, y=e.position.y}) end; '
    'local water=0; for x=-10,10 do for y=-10,10 do local t=surf.get_tile(' + str(BX) + '+x,' + str(BY) + '+y); if t and not t.valid then water=water+1 end end end; '
    'helpers.write_file("octave_minimal_debug.json", helpers.table_to_json({chunk_generated=gen, all=all, water=water, tick=game.tick}), false)'
)
with open("octave_minimal_debug_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
