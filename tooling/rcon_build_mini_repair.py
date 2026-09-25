"""Build the mini repair blueprint (269 genuinely-missing arithmetic-
combinators) via RCON, at the same target position as the original build.
Uses a dedicated file (not an inline bash -c invocation) to avoid any
shell-quoting corruption of the embedded blueprint string.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from rcon_client import connect

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "scratch_mini_repair_bp.txt")
TARGET_X = -220
TARGET_Y = 90

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

with connect(timeout=30.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
