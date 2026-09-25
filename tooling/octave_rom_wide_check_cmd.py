BX, BY = 650, 700
area = "{{" + str(BX - 300) + "," + str(BY - 300) + "},{" + str(BX + 300) + "," + str(BY + 300) + "}}"
cmd = (
    '/c local surf=game.player.surface; local counts={}; local ghosts=0; local sample={}; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do '
    'counts[e.type]=(counts[e.type] or 0)+1; '
    'if e.type=="entity-ghost" then ghosts=ghosts+1; '
    'if #sample<20 then table.insert(sample, {ghost_name=e.ghost_name, x=e.position.x, y=e.position.y}) end end end; '
    'helpers.write_file("octave_rom_wide_check.json", helpers.table_to_json({counts=counts, ghosts=ghosts, sample=sample}), false)'
)
with open("octave_rom_wide_check_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
