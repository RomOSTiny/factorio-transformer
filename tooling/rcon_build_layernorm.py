"""Build the LayerNorm full-test blueprint (4439 entities) via RCON.

Adapts the AUTOMATION.md manual-console build template for RCON: no
game.player (nil over RCON, see CLAUDE.md) -- use game.players[1],
game.surfaces["nauvis"], game.forces["player"] instead. Target area
(-300,0)-(300,900) was recon'd clean (0 entities, 0 water tiles).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from rcon_client import connect

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_layernorm_full_test_blueprint.txt")
TARGET_X = -220
TARGET_Y = 90

with open(BLUEPRINT_PATH, "r", encoding="utf-8") as f:
    bp_string = f.read().strip()

assert '"' not in bp_string and "\\" not in bp_string, "blueprint string has chars unsafe for a Lua double-quoted literal"

lua = (
    'local inv = game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    f'local ok = inv[1].import_stack("{bp_string}"); '
    f'local built = inv[1].build_blueprint{{surface=game.surfaces["nauvis"], force=game.forces["player"], position={{x={TARGET_X}, y={TARGET_Y}}}}}; '
    'local n = built and #built or -1; '
    "inv.destroy(); "
    'helpers.write_file("build.json", helpers.table_to_json({import_ok=ok, entities_built=n}), false); '
    "rcon.print(n)"
)

with connect(timeout=30.0) as c:
    resp = c.command("/c " + lua)
    print("entities_built (rcon.print):", resp.strip())
