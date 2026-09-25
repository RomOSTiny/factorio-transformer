with open("proc_demo_blueprint.txt") as f:
    bp = f.read()

cmd = (
    '/c local inv=game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    f'local ok=inv[1].import_stack("{bp}"); '
    'local built=inv[1].build_blueprint{surface=game.player.surface, force=game.player.force, position={x=200,y=200}}; '
    'local n = built and #built or -1; '
    'inv.destroy(); '
    'helpers.write_file("build_blueprint_test.json", helpers.table_to_json({import_ok=ok, entities_built=n}), false)'
)
with open("build_blueprint_cmd.txt", "w") as f:
    f.write(cmd)
print("Command length:", len(cmd))
