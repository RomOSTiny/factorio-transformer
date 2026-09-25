"""Recon for a brand-new world: anchor = player position + (50,50) offset
(clears the immediate spawn point), reports back the exact numeric anchor
so the following build command can hardcode the same BX,BY (not recompute
from player position again, in case the player moves)."""
cmd = (
    '/c local surf=game.player.surface; local p=game.player.position; '
    'local bx,by=math.floor(p.x+50), math.floor(p.y+50); '
    'game.forces.player.chart(surf, {{bx-350,by-350},{bx+350,by+350}}); '
    'local area={{bx-20,by-20},{bx+190,by+100}}; '
    'local counts={}; local biters=0; '
    'for _,e in pairs(surf.find_entities_filtered{area=area}) do '
    'counts[e.type]=(counts[e.type] or 0)+1; '
    'if e.type=="unit-spawner" or e.type=="unit" then biters=biters+1 end end; '
    'helpers.write_file("octave_rom_nw_recon.json", helpers.table_to_json({bx=bx, by=by, counts=counts, biters=biters}), false)'
)
with open("octave_rom_newworld_recon_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
