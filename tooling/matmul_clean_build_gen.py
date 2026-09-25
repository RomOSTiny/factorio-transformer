with open("stage2_matmul_test_blueprint.txt") as f:
    bp = f.read()

BX, BY = 1000, 1000
RADIUS = 20  # chunks; design bbox is 462x420 tiles (~15x14 chunks), generous margin
AX1, AY1, AX2, AY2 = BX - 300, BY - 280, BX + 300, BY + 280
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

cmd = (
    '/c game.player.surface.request_to_generate_chunks({x=' + str(BX) + ',y=' + str(BY) + '}, ' + str(RADIUS) + '); '
    'game.player.surface.force_generate_chunk_requests(); '
    'local inv=game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    'local ok=inv[1].import_stack("' + bp + '"); '
    'local built=inv[1].build_blueprint{surface=game.player.surface, force=game.player.force, position={x=' + str(BX) + ',y=' + str(BY) + '}}; '
    'local n = built and #built or -1; '
    'inv.destroy(); '
    'local revived, failed = 0, 0; '
    'for _, e in pairs(game.player.surface.find_entities_filtered{type="entity-ghost", area=' + area + '}) do '
    'local rok = pcall(function() e.revive() end); if rok then revived=revived+1 else failed=failed+1 end end; '
    'helpers.write_file("clean_build_result.json", helpers.table_to_json({import_ok=ok, entities_built=n, revived=revived, failed=failed}), false)'
)
with open("matmul_clean_build_cmd.txt", "w") as f:
    f.write(cmd)
print("written, len=", len(cmd))
print("build position:", BX, BY, " chunk radius:", RADIUS, " revive area:", area)
