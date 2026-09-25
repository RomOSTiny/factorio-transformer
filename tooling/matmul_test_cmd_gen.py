with open("stage2_matmul_test_blueprint.txt") as f:
    bp = f.read()

BX, BY = 600, 600
AX1, AY1, AX2, AY2 = BX - 50, BY - 50, BX + 50, BY + 50

build_cmd = (
    '/c game.player.surface.request_to_generate_chunks({x=' + str(BX) + ',y=' + str(BY) + '}, 3); '
    'game.player.surface.force_generate_chunk_requests(); '
    'local inv=game.create_inventory(1); '
    'inv[1].set_stack{name="blueprint"}; '
    'local ok=inv[1].import_stack("' + bp + '"); '
    'local built=inv[1].build_blueprint{surface=game.player.surface, force=game.player.force, position={x=' + str(BX) + ',y=' + str(BY) + '}}; '
    'local n = built and #built or -1; '
    'inv.destroy(); '
    'helpers.write_file("matmul_test_build.json", helpers.table_to_json({import_ok=ok, entities_built=n}), false)'
)
with open("matmul_test_build_cmd.txt", "w") as f:
    f.write(build_cmd)

area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

revive_cmd = (
    '/c local n=0; local failed=0; '
    'for _, e in pairs(game.player.surface.find_entities_filtered{type="entity-ghost", area=' + area + '}) do '
    'local ok = pcall(function() e.revive() end); if ok then n=n+1 else failed=failed+1 end end; '
    'helpers.write_file("matmul_test_revive.json", helpers.table_to_json({revived=n, failed=failed}), false)'
)
with open("matmul_test_revive_cmd.txt", "w") as f:
    f.write(revive_cmd)

verify_cmd = (
    '/c local out={}; '
    'for _,e in pairs(game.player.surface.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}) do '
    'local ok,signals=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local sp={}; if ok and signals then for _,s in pairs(signals) do if s.signal.name=="signal-A" then sp[#sp+1]={name=s.signal.name,count=s.count} end end end; '
    'if #sp>0 then out[#out+1]={x=e.position.x,y=e.position.y,output=sp} end end; '
    'helpers.write_file("matmul_test_verify.json", helpers.table_to_json(out), false)'
)
with open("matmul_test_verify_cmd.txt", "w") as f:
    f.write(verify_cmd)

print("Commands written. Build area:", BX, BY)
