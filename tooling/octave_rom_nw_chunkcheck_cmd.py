BX, BY = 50, 50
cmd = (
    '/c local surf=game.player.surface; local ungenerated=0; local n=0; local sample={}; '
    'for cx=' + str((BX - 20) // 32) + ',' + str((BX + 190) // 32) + ' do '
    'for cy=' + str((BY - 20) // 32) + ',' + str((BY + 100) // 32) + ' do '
    'n=n+1; local ok=surf.is_chunk_generated({cx,cy}); '
    'if not ok then ungenerated=ungenerated+1; if #sample<5 then table.insert(sample,{cx,cy}) end end end end; '
    'helpers.write_file("octave_rom_nw_chunkcheck.json", helpers.table_to_json({checked=n, ungenerated=ungenerated, sample=sample}), false)'
)
with open("octave_rom_nw_chunkcheck_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
