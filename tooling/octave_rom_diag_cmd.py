"""Concise diagnostic: counts + bbox of everything in a wide area around
(650,700), split into real vs ghost, to find out where the build actually
landed and whether there's duplication (recon confirmed this whole area
was empty before this session's build attempts)."""
BX, BY = 650, 700
area = "{{" + str(BX - 350) + "," + str(BY - 350) + "},{" + str(BX + 350) + "," + str(BY + 350) + "}}"
cmd = (
    '/c local surf=game.player.surface; local counts={}; local gcounts={}; '
    'local minx,maxx,miny,maxy=1e9,-1e9,1e9,-1e9; local n=0; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do n=n+1; '
    'local x,y=e.position.x,e.position.y; if x<minx then minx=x end; if x>maxx then maxx=x end; '
    'if y<miny then miny=y end; if y>maxy then maxy=y end; '
    'if e.type=="entity-ghost" then gcounts[e.ghost_name]=(gcounts[e.ghost_name] or 0)+1 '
    'else counts[e.type]=(counts[e.type] or 0)+1 end end; '
    'helpers.write_file("octave_rom_diag.json", helpers.table_to_json({n=n, real_counts=counts, ghost_counts=gcounts, bbox={minx,miny,maxx,maxy}}), false)'
)
with open("octave_rom_diag_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
