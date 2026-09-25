cmd = (
    '/c local out={}; '
    'local ok,q=pcall(function() return prototypes.quality["legendary"] end); '
    'out.legendary_exists = ok and q~=nil; '
    'out.force_name = game.player.force.name; '
    'out.character_present = game.player.character ~= nil; '
    'out.controller_type = game.player.controller_type; '
    'helpers.write_file("octave_rom_nw_qualitycheck.json", helpers.table_to_json(out), false)'
)
with open("octave_rom_nw_qualitycheck_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
