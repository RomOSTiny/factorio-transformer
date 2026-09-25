"""Build the Attention full-test blueprint via RCON, same pattern as
rcon_build_layernorm.py. Target area (-1100,-500)-(-500,1300) recon'd
clean (0 entities, 0 water, 0 biter spawners)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from rcon_client import connect

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_attention_full_test_blueprint.txt")
TARGET_X = -800
TARGET_Y = 400

with open(BLUEPRINT_PATH, "r", encoding="utf-8") as f:
    bp_string = f.read().strip()

assert '"' not in bp_string and "\\" not in bp_string

lua = (
    'local inv = game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    f'local ok = inv[1].import_stack("{bp_string}"); '
    f'local built = inv[1].build_blueprint{{surface=game.surfaces["nauvis"], force=game.forces["player"], position={{x={TARGET_X}, y={TARGET_Y}}}}}; '
    'local n = built and #built or -1; '
    "inv.destroy(); "
    'rcon.print("import_ok=" .. tostring(ok) .. " entities_built=" .. n)'
)

with connect(timeout=60.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
