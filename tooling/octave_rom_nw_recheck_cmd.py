BX, BY = 50, 50
area = "{{" + str(BX - 350) + "," + str(BY - 350) + "},{" + str(BX + 350) + "," + str(BY + 350) + "}}"
cmd = (
    '/c local surf=game.player.surface; local n=0; local ghosts=0; '
    'local minx,maxx,miny,maxy=1e9,-1e9,1e9,-1e9; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do n=n+1; '
    'if e.type=="entity-ghost" then ghosts=ghosts+1 end; '
    'local x,y=e.position.x,e.position.y; if x<minx then minx=x end; if x>maxx then maxx=x end; '
    'if y<miny then miny=y end; if y>maxy then maxy=y end end; '
    'helpers.write_file("octave_rom_nw_recheck.json", helpers.table_to_json({n=n, ghosts=ghosts, bbox={minx,miny,maxx,maxy}}), false)'
)
with open("octave_rom_nw_recheck_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
