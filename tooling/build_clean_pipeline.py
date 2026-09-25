"""
Reshenie 25 RESUME POINT, clean rebuild on a brand-new world (user's choice,
to avoid clutter from the old (900,900)/(900,1400)/(900,2000)/(1000,1000)
test builds and the botched non-idempotent repair run at (1000,1000)).

Step 1/2 of the pipeline: generate chunks + build blueprint, then (separate
command) revive ghosts and, in the SAME command, locate t_ctr to read back
its REAL world position. We do NOT trust an analytically-computed offset
(bbox center from entity .position min/max would miss any footprint-size
correction build_blueprint's own bbox math applies) - we measure it live
instead: t_ctr's known local position is exactly (0.5, 1.0), so
OX = real_x - 0.5, OY = real_y - 1.0 gives the exact local->world offset
for every other position in the manifest, no guessing.
"""
BX, BY = -1500, -1500  # eighth spot (4 unit-spawners per recon, accepted -
# this whole region has a biter base, several recon attempts found 5-17
# spawners at every nearby candidate) - testing fix v3 (pulse moved to
# K//2, mid-window, instead of chasing an exact tick offset between O/P)
# this run adds the comprehensive
# per-firing P-value logger (gate_logger_cmd.txt) to see EXACTLY which
# in_idx/out_idx term each gate actually adds, not just the frozen final
# sum - (1300,500)'s repair was topologically clean (has_edge fallback_used
# =0) yet produced acc_3..acc_11 values that are WRONG but reproducible
# bit-for-bit vs an earlier independent build, so this is a deterministic
# logic bug in the design itself, not revive/repair flakiness - (500,1900)'s gate-output logger ran a
# FULL valid sweep (T=55028>54000) with topologically-verified wiring and
# recorded ZERO firings on any of the 12 gates; separately, watching gate_0
# raw input directly confirmed signal-M correctly pulses to 899 every 900
# ticks. So the remaining open question is whether signal-O is ever
# actually 0 (matching gate_0's own constant) AT THE SAME TICK M hits 899 -
# this run logs (O,M) at gate_0 every time M==899 across the whole sweep,
# from tick 0, to answer that directly.
RADIUS = 15  # chunks
AX1, AY1, AX2, AY2 = BX - 280, BY - 250, BX + 280, BY + 250
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

with open("stage2_matmul_test_blueprint.txt") as f:
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
    'helpers.write_file("clean_build.json", helpers.table_to_json({import_ok=ok, entities_built=n}), false)'
)
with open("clean_build_cmd.txt", "w") as f:
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
    'helpers.write_file("clean_revive.json", helpers.table_to_json({revived=revived, failed=failed, tctr_pos=tpos}), false)'
)
with open("clean_revive_offset_cmd.txt", "w") as f:
    f.write(revive_offset_cmd)

print("build_cmd bytes:", len(build_cmd))
print("revive_offset_cmd bytes:", len(revive_offset_cmd))
print("area:", area)
print(f"BX,BY={BX},{BY}")
