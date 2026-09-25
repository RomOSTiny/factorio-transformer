"""
Build + revive + offset-measurement for the octave/subbucket isolated test,
same pipeline shape as build_clean_pipeline.py (Reshenie 25/26): import the
blueprint via inventory.import_stack/build_blueprint (no manual Import
string), revive ghosts with pcall (Reshenie 15's lesson - unprotected
revive() aborts the whole batch on the first invalid ghost), then locate
t_ctr live to get the exact local->world offset (Reshenie 26: bounding-box
math is NOT trustworthy for this, t_ctr's local position is known exactly
as (0.5, 1.0), so OX=real_x-0.5, OY=real_y-1.0).
"""
BX, BY = 350, 0
RADIUS = 15
AX1, AY1, AX2, AY2 = BX - 250, BY - 260, BX + 250, BY + 260
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

with open("stage2_octave_isolated_test_blueprint.txt") as f:
    bp = f.read()

build_cmd = (
    '/c game.player.surface.request_to_generate_chunks({x=' + str(BX) + ',y=' + str(BY) + '}, ' + str(RADIUS) + '); '
    'game.player.surface.force_generate_chunk_requests(); '
    'local inv=game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    'local ok=inv[1].import_stack("' + bp + '"); '
    'local built=inv[1].build_blueprint{surface=game.player.surface, force=game.player.force, position={x=' + str(BX) + ',y=' + str(BY) + '}}; '
    'local n = built and #built or -1; '
    'inv.destroy(); '
    'helpers.write_file("octave_build.json", helpers.table_to_json({import_ok=ok, entities_built=n}), false)'
)
with open("octave_build_cmd.txt", "w") as f:
    f.write(build_cmd)

revive_offset_cmd = (
    '/c local surf=game.player.surface; local revived,failed=0,0; '
    'for _,e in pairs(surf.find_entities_filtered{type="entity-ghost", area=' + area + '}) do '
    'local rok=pcall(function() e.revive() end); if rok then revived=revived+1 else failed=failed+1 end end; '
    'local tpos=nil; '
    'for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}) do '
    'local cb=e.get_control_behavior(); '
    'if cb and cb.parameters and cb.parameters.output_signal and cb.parameters.output_signal.name=="signal-T" '
    'and cb.parameters.first_signal and cb.parameters.first_signal.name=="signal-T" and cb.parameters.operation=="+" then '
    'tpos={x=e.position.x,y=e.position.y}; break end end; '
    'helpers.write_file("octave_revive.json", helpers.table_to_json({revived=revived, failed=failed, tctr_pos=tpos}), false)'
)
with open("octave_revive_cmd.txt", "w") as f:
    f.write(revive_offset_cmd)

print("build_cmd bytes:", len(build_cmd))
print("revive_offset_cmd bytes:", len(revive_offset_cmd))
print(f"BX,BY={BX},{BY}")
