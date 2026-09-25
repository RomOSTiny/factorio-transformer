"""Generates recon/build/revive/census Lua commands for
octave_minimal_rom_test.py's blueprint, at a fresh location near the
already-used (350,0) and (500,700) spots (per session hand-off note -
recon is mandatory before first build on new ground, biter nests silently
give entities_built=0)."""
BX, BY = 650, 700
# local bbox from octave_minimal_rom_test.py: x=[-3,168] y=[-6,79]
AX1, AY1, AX2, AY2 = BX - 20, BY - 20, BX + 190, BY + 100
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

with open("octave_minimal_rom_test_blueprint.txt") as f:
    bp = f.read()

recon_cmd = (
    '/c local surf=game.player.surface; '
    'game.forces.player.chart(surf, {{' + str(BX - 100) + ',' + str(BY - 100) + '},{' + str(BX + 300) + ',' + str(BY + 200) + '}}); '
    'local counts={}; local biters=0; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do '
    'counts[e.type]=(counts[e.type] or 0)+1; '
    'if e.type=="unit-spawner" or e.type=="unit" then biters=biters+1 end end; '
    'helpers.write_file("octave_rom_recon.json", helpers.table_to_json({counts=counts, biters=biters}), false)'
)
with open("octave_rom_recon_cmd.txt", "w") as f:
    f.write(recon_cmd)

build_cmd = (
    '/c local inv=game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    'local ok=inv[1].import_stack("' + bp + '"); '
    'local built=inv[1].build_blueprint{surface=game.player.surface, force=game.player.force, position={x=' + str(BX) + ',y=' + str(BY) + '}}; '
    'local n = built and #built or -1; '
    'inv.destroy(); '
    'helpers.write_file("octave_rom_build.json", helpers.table_to_json({import_ok=ok, entities_built=n}), false)'
)
with open("octave_rom_build_cmd.txt", "w") as f:
    f.write(build_cmd)

revive_cmd = (
    '/c local surf=game.player.surface; local revived,failed=0,0; '
    'for _,e in pairs(surf.find_entities_filtered{type="entity-ghost", area=' + area + '}) do '
    'local rok=pcall(function() e.revive() end); if rok then revived=revived+1 else failed=failed+1 end end; '
    'helpers.write_file("octave_rom_revive.json", helpers.table_to_json({revived=revived, failed=failed}), false)'
)
with open("octave_rom_revive_cmd.txt", "w") as f:
    f.write(revive_cmd)

census_cmd = (
    '/c local surf=game.player.surface; local counts={}; local ghosts=0; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do '
    'counts[e.type]=(counts[e.type] or 0)+1; if e.type=="entity-ghost" then ghosts=ghosts+1 end end; '
    'helpers.write_file("octave_rom_census.json", helpers.table_to_json({counts=counts, ghosts=ghosts}), false)'
)
with open("octave_rom_census_cmd.txt", "w") as f:
    f.write(census_cmd)

print("BX,BY =", BX, BY)
print("recon bytes:", len(recon_cmd))
print("build bytes:", len(build_cmd))
print("revive bytes:", len(revive_cmd))
print("census bytes:", len(census_cmd))
