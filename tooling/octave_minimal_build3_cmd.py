BX, BY = 500, 700
RADIUS = 5
AX1, AY1, AX2, AY2 = BX - 30, BY - 30, BX + 30, BY + 30
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

with open("octave_minimal_isolated_test_blueprint.txt") as f:
    bp = f.read()

recon_cmd = (
    '/c local surf=game.player.surface; '
    'surf.request_to_generate_chunks({x=' + str(BX) + ',y=' + str(BY) + '}, ' + str(RADIUS) + '); '
    'surf.force_generate_chunk_requests(); '
    'local counts={}; for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do counts[e.type]=(counts[e.type] or 0)+1 end; '
    'helpers.write_file("octave_minimal_recon3.json", helpers.table_to_json({counts=counts}), false)'
)
with open("octave_minimal_recon3_cmd.txt", "w") as f:
    f.write(recon_cmd)

build_cmd = (
    '/c game.player.surface.request_to_generate_chunks({x=' + str(BX) + ',y=' + str(BY) + '}, ' + str(RADIUS) + '); '
    'game.player.surface.force_generate_chunk_requests(); '
    'local inv=game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    'local ok=inv[1].import_stack("' + bp + '"); '
    'local built=inv[1].build_blueprint{surface=game.player.surface, force=game.player.force, position={x=' + str(BX) + ',y=' + str(BY) + '}}; '
    'local n = built and #built or -1; '
    'inv.destroy(); '
    'helpers.write_file("octave_minimal_build3.json", helpers.table_to_json({entities_built=n}), false)'
)
with open("octave_minimal_build3_cmd.txt", "w") as f:
    f.write(build_cmd)

revive_cmd = (
    '/c local surf=game.player.surface; local revived,failed=0,0; '
    'for _,e in pairs(surf.find_entities_filtered{type="entity-ghost", area=' + area + '}) do '
    'local rok=pcall(function() e.revive() end); if rok then revived=revived+1 else failed=failed+1 end end; '
    'helpers.write_file("octave_minimal_revive3.json", helpers.table_to_json({revived=revived, failed=failed}), false)'
)
with open("octave_minimal_revive3_cmd.txt", "w") as f:
    f.write(revive_cmd)

print("recon bytes:", len(recon_cmd))
print("build bytes:", len(build_cmd))
