"""Build/revive/wide-diag commands for the new world, anchored at (50,50)
(confirmed clean by recon: 0 entities, 0 biters in the build footprint)."""
BX, BY = 50, 50
AX1, AY1, AX2, AY2 = BX - 20, BY - 20, BX + 190, BY + 100
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"
wide_area = "{{" + str(BX - 350) + "," + str(BY - 350) + "},{" + str(BX + 350) + "," + str(BY + 350) + "}}"

with open("octave_minimal_rom_test_blueprint.txt") as f:
    bp = f.read()

build_cmd = (
    '/c local inv=game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    'local ok=inv[1].import_stack("' + bp + '"); '
    'local built=inv[1].build_blueprint{surface=game.player.surface, force=game.player.force, position={x=' + str(BX) + ',y=' + str(BY) + '}}; '
    'local n = built and #built or -1; '
    'inv.destroy(); '
    'helpers.write_file("octave_rom_nw_build.json", helpers.table_to_json({import_ok=ok, entities_built=n}), false)'
)
with open("octave_rom_nw_build_cmd.txt", "w") as f:
    f.write(build_cmd)

# wide diagnostic: locate ACTUAL entity bbox after build, before assuming
# anything about where local (0,0) landed (Reshenie: got burned by this
# assumption on the previous attempt).
diag_cmd = (
    '/c local surf=game.player.surface; local counts={}; local gcounts={}; '
    'local minx,maxx,miny,maxy=1e9,-1e9,1e9,-1e9; local n=0; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + wide_area + '}) do n=n+1; '
    'local x,y=e.position.x,e.position.y; if x<minx then minx=x end; if x>maxx then maxx=x end; '
    'if y<miny then miny=y end; if y>maxy then maxy=y end; '
    'if e.type=="entity-ghost" then gcounts[e.ghost_name]=(gcounts[e.ghost_name] or 0)+1 '
    'else counts[e.type]=(counts[e.type] or 0)+1 end end; '
    'helpers.write_file("octave_rom_nw_diag.json", helpers.table_to_json({n=n, real_counts=counts, ghost_counts=gcounts, bbox={minx,miny,maxx,maxy}}), false)'
)
with open("octave_rom_nw_diag_cmd.txt", "w") as f:
    f.write(diag_cmd)

revive_cmd = (
    '/c local surf=game.player.surface; local revived,failed=0,0; '
    'for _,e in pairs(surf.find_entities_filtered{type="entity-ghost", area=' + wide_area + '}) do '
    'local rok=pcall(function() e.revive() end); if rok then revived=revived+1 else failed=failed+1 end end; '
    'helpers.write_file("octave_rom_nw_revive.json", helpers.table_to_json({revived=revived, failed=failed}), false)'
)
with open("octave_rom_nw_revive_cmd.txt", "w") as f:
    f.write(revive_cmd)

census_cmd = (
    '/c local surf=game.player.surface; local counts={}; local ghosts=0; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + wide_area + '}) do '
    'counts[e.type]=(counts[e.type] or 0)+1; if e.type=="entity-ghost" then ghosts=ghosts+1 end end; '
    'helpers.write_file("octave_rom_nw_census.json", helpers.table_to_json({counts=counts, ghosts=ghosts}), false)'
)
with open("octave_rom_nw_census_cmd.txt", "w") as f:
    f.write(census_cmd)

print("BX,BY =", BX, BY)
print("build bytes:", len(build_cmd))
print("diag bytes:", len(diag_cmd))
print("revive bytes:", len(revive_cmd))
print("census bytes:", len(census_cmd))
