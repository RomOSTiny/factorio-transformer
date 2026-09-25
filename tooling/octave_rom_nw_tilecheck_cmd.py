BX, BY = 50, 50
cmd = (
    '/c local surf=game.player.surface; local bad={}; local n=0; '
    'for x=' + str(BX - 20) + ',' + str(BX + 190) + ',4 do '
    'for y=' + str(BY - 20) + ',' + str(BY + 100) + ',4 do '
    'n=n+1; local t=surf.get_tile(x,y); '
    'if not t.valid or t.name=="water" or t.name=="deepwater" or string.find(t.name,"water") then '
    'table.insert(bad, {x=x,y=y,name=t.name}) end end end; '
    'helpers.write_file("octave_rom_nw_tilecheck.json", helpers.table_to_json({checked=n, bad_count=#bad, bad_sample={bad[1],bad[2],bad[3],bad[4],bad[5]}}), false)'
)
with open("octave_rom_nw_tilecheck_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
