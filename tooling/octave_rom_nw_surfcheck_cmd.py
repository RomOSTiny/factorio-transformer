cmd = (
    '/c local out={}; '
    'out.surface_name = game.player.surface.name; '
    'out.surface_valid = game.player.surface.valid; '
    'out.player_position = {game.player.position.x, game.player.position.y}; '
    'out.cheat_mode = game.player.cheat_mode; '
    'out.render_mode = game.player.render_mode; '
    'local ok,inv=pcall(function() '
    'local i=game.create_inventory(1); i[1].set_stack{name="blueprint"}; '
    'return i[1].valid, i[1].count end); '
    'out.inv_stack_ok = ok; '
    'helpers.write_file("octave_rom_nw_surfcheck.json", helpers.table_to_json(out), false)'
)
with open("octave_rom_nw_surfcheck_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
