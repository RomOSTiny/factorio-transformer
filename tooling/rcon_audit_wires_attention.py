"""Audit pass: find manifest edges where the widened (1.5-tile) find_near
tolerance used by rcon_repair_wires_attention.py could have matched an
AMBIGUOUS or WRONG entity -- i.e., where more than one live entity of the
expected name exists within 1.5 tiles of the expected position (only one
of them can be correct; the others are false-positive risks that may have
been wired in error, exactly as found live for p1_0<->p0_0)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

ARITH_OX, ARITH_OY = -2912.5, -273.0
CONST_OX, CONST_OY = -2913.0, -273.0
WIRED_TYPES = {"constant-combinator", "arithmetic-combinator", "decider-combinator"}

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_attention_full_test_blueprint.txt")
bp_string = open(BLUEPRINT_PATH, encoding="utf-8").read().strip()
bp = get_blueprintable_from_string(bp_string)
d = bp.to_dict()["blueprint"]
entities = d["entities"]
wires = d["wires"]


def real_pos(ent):
    lx, ly = ent["position"]["x"], ent["position"]["y"]
    if ent["name"] in ("arithmetic-combinator", "decider-combinator"):
        return lx + ARITH_OX, ly + ARITH_OY
    return lx + CONST_OX, ly + CONST_OY


manifest = []
for e1n, c1, e2n, c2 in wires:
    ent1, ent2 = entities[e1n - 1], entities[e2n - 1]
    if ent1["name"] not in WIRED_TYPES or ent2["name"] not in WIRED_TYPES:
        continue
    x1, y1 = real_pos(ent1)
    x2, y2 = real_pos(ent2)
    manifest.append([ent1["name"], round(x1, 3), round(y1, 3), c1, ent2["name"], round(x2, 3), round(y2, 3), c2])

manifest_json = json.dumps(manifest)
print(f"manifest entries: {len(manifest)}")

lua = '''
local surf = game.surfaces["nauvis"]
local W = helpers.json_to_table("__MANIFEST__")

local by_name = {}
for _, name in pairs({"constant-combinator", "arithmetic-combinator", "decider-combinator"}) do
  by_name[name] = surf.find_entities_filtered{name=name, area={{-1100,-500},{-500,1300}}}
end

local function count_within(name, x, y, tol)
  local n = 0
  for _, e in pairs(by_name[name]) do
    if math.abs(e.position.x-x) < tol and math.abs(e.position.y-y) < tol then n = n + 1 end
  end
  return n
end

local ambiguous = {}
for i = 1, #W do
  local w = W[i]
  local n1 = count_within(w[1], w[2], w[3], 1.5)
  local n2 = count_within(w[5], w[6], w[7], 1.5)
  if n1 > 1 or n2 > 1 then
    table.insert(ambiguous, w[1] .. "@" .. w[2] .. "," .. w[3] .. "(n=" .. n1 .. ") <-> " .. w[5] .. "@" .. w[6] .. "," .. w[7] .. "(n=" .. n2 .. ")")
  end
end
rcon.print("ambiguous_edges=" .. #ambiguous)
helpers.write_file("audit_wires_attention.json", helpers.table_to_json(ambiguous), false)
'''.strip()

lua = lua.replace("__MANIFEST__", manifest_json.replace("\\", "\\\\").replace('"', '\\"'))

with connect(timeout=120.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
