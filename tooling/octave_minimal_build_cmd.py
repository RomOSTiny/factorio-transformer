BX, BY = 500, 500
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
    'helpers.write_file("octave_minimal_recon.json", helpers.table_to_json({counts=counts}), false)'
)
with open("octave_minimal_recon_cmd.txt", "w") as f:
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
    'local revived,failed=0,0; '
    'for _,e in pairs(game.player.surface.find_entities_filtered{type="entity-ghost", area=' + area + '}) do '
    'local rok=pcall(function() e.revive() end); if rok then revived=revived+1 else failed=failed+1 end end; '
    'helpers.write_file("octave_minimal_build.json", helpers.table_to_json({entities_built=n, revived=revived, failed=failed}), false)'
)
with open("octave_minimal_build_cmd.txt", "w") as f:
    f.write(build_cmd)

# persistent logger watching o_collect EVERY tick (not just on change) -
# find it by CONFIG (unique first_signal=signal-I, op=+, output=signal-O
# in this tiny blueprint), not by an assumed position - build_blueprint
# centers the blueprint's bbox at (BX,BY), NOT its local (0,0) origin, so
# an analytically-computed offset would be wrong (Reshenie 26: measure
# live, don't compute), and a config search sidesteps needing the offset
# at all for a blueprint this small.
logger_cmd = (
    '/c local surf=game.player.surface; local o=nil; '
    'for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}) do '
    'local cb=e.get_control_behavior(); local p=(cb and cb.parameters); '
    'if p and p.first_signal and p.first_signal.name=="signal-I" and p.operation=="+" and p.output_signal and p.output_signal.name=="signal-O" then o=e break end end; '
    'local found = o~=nil; '
    'local log={}; local start_tick=game.tick; '
    'script.on_event(defines.events.on_tick, function(event) '
    'if o and o.valid then '
    'local ok,sout=pcall(function() return o.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local cur=0; if ok and sout then for _,s in pairs(sout) do if s.signal.name=="signal-O" then cur=s.count end end end; '
    'log[#log+1]={t=event.tick-start_tick, o=cur}; '
    'if #log > 3600 then table.remove(log,1) end end '
    'if event.tick % 300 == 0 then '
    'helpers.write_file("octave_minimal_log.json", helpers.table_to_json({log=log, found=found}), false) '
    'end end); '
    'helpers.write_file("octave_minimal_log.json", helpers.table_to_json({log=log, found=found}), false); '
    'game.print("minimal logger registered, found: "..tostring(found))'
)
with open("octave_minimal_logger_cmd.txt", "w") as f:
    f.write(logger_cmd)

print("recon bytes:", len(recon_cmd))
print("build bytes:", len(build_cmd))
print("logger bytes:", len(logger_cmd))
