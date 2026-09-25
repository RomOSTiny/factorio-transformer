cmd = (
    '/c local surf=game.player.surface; local o=nil; '
    'for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", area={{470,670},{530,730}}}) do '
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
    'helpers.write_file("octave_minimal_log3.json", helpers.table_to_json({log=log, found=found}), false) '
    'end end); '
    'helpers.write_file("octave_minimal_log3.json", helpers.table_to_json({log=log, found=found}), false); '
    'game.print("minimal logger3 registered, found: "..tostring(found))'
)
with open("octave_minimal_logger3_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
