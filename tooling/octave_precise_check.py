"""
Position-only fuzzy matching proved unreliable in this densely-packed
region (a single real gap can make an optimal spatial assignment report a
"phantom" missing/extra pair at the WRONG nearby position, since many relay
entities sit within 0.6-1.5 tiles of each other and share near-identical
config). Definitive check instead: for EACH of the 366 expected
arithmetic-combinators individually, query a small box at its own exact
position AND require the found entity's first_signal/operation/
output_signal to match what THIS SPECIFIC manifest entry expects - not just
"is anything nearby" (position alone can't disambiguate a dense chain of
near-identical relays) but "is the astronaut actually the right one".
"""
import base64
import zlib
import json

with open("stage2_octave_isolated_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
entities = data["blueprint"]["entities"]

OX, OY = 178.0, -199.0  # measured live: tctr_pos (178.5,-198) - local (0.5,1.0)

manifest = []
for e in entities:
    if e["name"] != "arithmetic-combinator":
        continue
    p = e["position"]
    ac = e.get("control_behavior", {}).get("arithmetic_conditions", {})
    fs = ac.get("first_signal", {}).get("name", "")
    op = ac.get("operation", "*")
    sc = ac.get("second_signal")
    sc_name = sc.get("name") if sc else None
    sconst = ac.get("second_constant", 0)
    os_ = ac.get("output_signal", {}).get("name", "")
    wx, wy = p["x"] + OX, p["y"] + OY
    manifest.append((wx, wy, fs, op, sc_name, sconst, os_))

print(f"manifest size: {len(manifest)}")

lua_entries = []
for wx, wy, fs, op, sc_name, sconst, os_ in manifest:
    sc_lua = f'"{sc_name}"' if sc_name else "nil"
    lua_entries.append(f'{{{wx},{wy},"{fs}","{op}",{sc_lua},{sconst},"{os_}"}}')
manifest_lua = "{" + ",".join(lua_entries) + "}"

cmd = (
    '/c local surf=game.player.surface; local M=' + manifest_lua + '; '
    'local bad={}; '
    'for i=1,#M do local m=M[i]; local wx,wy=m[1],m[2]; '
    'local found=surf.find_entities_filtered{type="arithmetic-combinator", area={{wx-0.6,wy-0.6},{wx+0.6,wy+0.6}}}; '
    'local ok=false; '
    'for _,e in pairs(found) do '
    'local cb=e.get_control_behavior(); local p=(cb and cb.parameters); '
    'if p and p.first_signal and p.first_signal.name==m[3] and p.operation==m[4] and '
    '((m[5]==nil and p.second_signal==nil and p.second_constant==m[6]) or (m[5]~=nil and p.second_signal and p.second_signal.name==m[5])) and '
    'p.output_signal and p.output_signal.name==m[7] then ok=true break end end; '
    'if not ok then table.insert(bad, {idx=i, wx=wx, wy=wy, fs=m[3], op=m[4], os=m[7], n_found=#found}) end end; '
    'helpers.write_file("octave_precise_check.json", helpers.table_to_json({bad=bad, total=#M}), false)'
)
with open("octave_precise_check_cmd.txt", "w") as f:
    f.write(cmd)
print("cmd bytes:", len(cmd))
