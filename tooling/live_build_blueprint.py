import sys
sys.path.insert(0, r"C:\Users\roma_\Desktop\factorio-ai\tooling")
import rcon_client

bp_path = sys.argv[1]
TARGET_X, TARGET_Y = float(sys.argv[2]), float(sys.argv[3])
chunk_radius = int(sys.argv[4]) if len(sys.argv) > 4 else 10

bp_string = open(bp_path, encoding="utf-8").read().strip()
assert '"' not in bp_string and "\\" not in bp_string

lua = (
    'local s = game.surfaces["nauvis"]; '
    f's.request_to_generate_chunks({{{TARGET_X},{TARGET_Y}}}, {chunk_radius}); '
    's.force_generate_chunk_requests(); '
    'local inv = game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    f'local ok = inv[1].import_stack("{bp_string}"); '
    f'local built = inv[1].build_blueprint{{surface=s, force=game.forces["player"], position={{x={TARGET_X}, y={TARGET_Y}}}, force_build=true}}; '
    'local n = built and #built or -1; '
    "inv.destroy(); "
    'rcon.print("import_ok=" .. tostring(ok) .. " entities_built=" .. n)'
)
c = rcon_client.connect(timeout=60.0)
print(c.command("/c " + lua))
c.close()
