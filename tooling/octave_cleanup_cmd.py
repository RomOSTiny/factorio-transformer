"""
Clear the (0,350) area (first build spot, confirmed clear of spawners by
recon twice) of everything left over from the earlier (buggy-wire) builds,
so it can be reused for the final, fixed rebuild - avoids scanning yet
another new area when this one is already known-good.
"""
BX, BY = 0, 350
AX1, AY1, AX2, AY2 = BX - 260, BY - 270, BX + 260, BY + 270
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"
cmd = (
    '/c local surf=game.player.surface; local n=0; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do '
    'if e.valid and e.name~="character" then local ok=pcall(function() e.destroy() end); if ok then n=n+1 end end end; '
    'helpers.write_file("octave_cleanup.json", helpers.table_to_json({destroyed=n}), false)'
)
with open("octave_cleanup_cmd.txt", "w") as f:
    f.write(cmd)
print("bytes:", len(cmd))
