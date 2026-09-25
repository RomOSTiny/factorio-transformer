"""Rebuild the minimal test using the SAME two-step process (build, then a
SEPARATE revive() pass) proven throughout this whole project - the combined
one-shot build+revive script used earlier gave an anomalous 0/0/0 report and
left the constant combinator's signal not actually driving its output
despite correct configuration, a symptom never seen with the standard
separate-steps process anywhere else in this session."""
BX, BY = 500, 600  # fresh spot, clear of the broken first attempt
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
    'helpers.write_file("octave_minimal_recon2.json", helpers.table_to_json({counts=counts}), false)'
)
with open("octave_minimal_recon2_cmd.txt", "w") as f:
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
    'helpers.write_file("octave_minimal_build2.json", helpers.table_to_json({entities_built=n}), false)'
)
with open("octave_minimal_build2_cmd.txt", "w") as f:
    f.write(build_cmd)

revive_cmd = (
    '/c local surf=game.player.surface; local revived,failed=0,0; '
    'for _,e in pairs(surf.find_entities_filtered{type="entity-ghost", area=' + area + '}) do '
    'local rok=pcall(function() e.revive() end); if rok then revived=revived+1 else failed=failed+1 end end; '
    'helpers.write_file("octave_minimal_revive2.json", helpers.table_to_json({revived=revived, failed=failed}), false)'
)
with open("octave_minimal_revive2_cmd.txt", "w") as f:
    f.write(revive_cmd)

print("recon bytes:", len(recon_cmd))
print("build bytes:", len(build_cmd))
print("revive bytes:", len(revive_cmd))
