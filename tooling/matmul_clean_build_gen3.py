with open("stage2_matmul_test_blueprint.txt") as f:
    bp = f.read()

BX, BY = 1000, 1000
RADIUS = 20  # chunks; design bbox is 462x420 tiles (~15x14 chunks), generous margin
AX1, AY1, AX2, AY2 = BX - 300, BY - 280, BX + 300, BY + 280
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

# 1) recon: generate chunks, report back what's actually there (resources /
# enemy nests / existing entities) before we try to build - this is exactly
# what silently caused entities_built=0 last session (Reshenie 23).
recon_cmd = (
    '/c game.player.surface.request_to_generate_chunks({x=' + str(BX) + ',y=' + str(BY) + '}, ' + str(RADIUS) + '); '
    'game.player.surface.force_generate_chunk_requests(); '
    'local counts={}; '
    'for _,e in pairs(game.player.surface.find_entities_filtered{area=' + area + '}) do '
    'counts[e.type] = (counts[e.type] or 0) + 1 end; '
    'helpers.write_file("clean_recon.json", helpers.table_to_json({counts=counts, tick=game.tick}), false)'
)
with open("matmul_clean_recon_cmd.txt", "w") as f:
    f.write(recon_cmd)

# 2) build only
build_cmd = (
    'local inv=game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    'local ok=inv[1].import_stack("' + bp + '"); '
    'local built=inv[1].build_blueprint{surface=game.player.surface, force=game.player.force, position={x=' + str(BX) + ',y=' + str(BY) + '}}; '
    'local n = built and #built or -1; '
    'inv.destroy(); '
    'helpers.write_file("clean_build.json", helpers.table_to_json({import_ok=ok, entities_built=n}), false)'
)
with open("matmul_clean_build_only_cmd.txt", "w") as f:
    f.write("/c " + build_cmd)

# 3) revive only
revive_cmd = (
    '/c local revived, failed = 0, 0; '
    'for _, e in pairs(game.player.surface.find_entities_filtered{type="entity-ghost", area=' + area + '}) do '
    'local rok = pcall(function() e.revive() end); if rok then revived=revived+1 else failed=failed+1 end end; '
    'helpers.write_file("clean_revive.json", helpers.table_to_json({revived=revived, failed=failed}), false)'
)
with open("matmul_clean_revive_cmd.txt", "w") as f:
    f.write(revive_cmd)

print("recon len:", len(recon_cmd))
print("build len:", len("/c " + build_cmd))
print("revive len:", len(revive_cmd))
print("area:", area)
