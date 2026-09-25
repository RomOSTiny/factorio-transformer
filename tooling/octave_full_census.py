"""
User's own good instinct (matches Reshenie 9/22's hard-won lesson): don't
assume "1 arithmetic-combinator repaired" accounts for all 3 revive
failures - the entity-repair pass only ever handles arithmetic-combinators
by design (gen_repair_entities.py's own convention), so if any of the 3
lost ghosts were a decider-combinator (a gate/ROM-read cell) or a
constant-combinator (a ROM STORE cell, i.e. actual data), those would still
be silently missing right now - the wire-repair pass can't fix a wire to
an entity that was never recreated. Full census across ALL entity types
(not just arithmetic) to find out for certain, not guess.
"""
import base64
import zlib
import json

OX, OY = -172.0, 151.0  # measured live: tctr_pos (-171.5,152) - local (0.5,1.0)

with open("stage2_octave_isolated_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]

# e["position"] in the exported blueprint JSON is ALREADY the real final
# local position draftsman computed (whatever internal tile_position->
# position quirk applies, Reshenie 26, is baked in there) - just add the
# measured GLOBAL offset, same as gen_repair_entities.py/gen_repair.py do.
# An earlier version of this script tried to re-derive a per-TYPE local
# offset from scratch instead of trusting e["position"] directly - wrong,
# because plenty of entities here (cmp_k, gate_i, t_ctr, ...) were built via
# position= with an ALREADY-fractional local X (e.g. cx+0.5), which does
# NOT get Reshenie 26's extra +0.5 shift (that only applies to
# tile_position= entities with an INTEGER local X) - a blanket per-type
# offset table conflated the two construction methods and produced
# hundreds of bogus "missing" entries that were really just this script's
# own arithmetic being off by the shift it wrongly re-added.
by_type = {}
for e in entities:
    name = e["name"]
    wx, wy = e["position"]["x"] + OX, e["position"]["y"] + OY
    by_type.setdefault(name, []).append((wx, wy, e["entity_number"]))

print("Expected counts by type:")
for name, lst in sorted(by_type.items()):
    print(f"  {name}: {len(lst)}")

# built via plain string concatenation (not an f-string) - Lua's nested-brace
# table syntax is error-prone to get right inside Python's own {{ }} escaping,
# same lesson as octave_recon_cmd.py's area string.
area = "{{" + str(-350) + "," + str(90) + "},{" + str(200) + "," + str(670) + "}}"
parts = ["/c local surf=game.player.surface; local out={}; "]
for name in by_type:
    var = name.replace("-", "_")
    parts.append('local found_' + var + '={}; ')
    parts.append(
        'for _,e in pairs(surf.find_entities_filtered{type="' + name + '", area=' + area + '}) do '
        'table.insert(found_' + var + ', {e.position.x, e.position.y}) end; '
        'out["' + name + '"]=found_' + var + '; '
    )
parts.append('helpers.write_file("octave_census.json", helpers.table_to_json(out), false)')
cmd = "".join(parts)
with open("octave_census_cmd.txt", "w") as f:
    f.write(cmd)
print(f"\ncensus cmd bytes: {len(cmd)}")

with open("octave_census_expected.json", "w") as f:
    json.dump({name: [[x, y] for x, y, _ in lst] for name, lst in by_type.items()}, f)
print("saved octave_census_expected.json")
