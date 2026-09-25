"""
Compact (O,M) tracer at gate_0 for the WHOLE sweep, registered right after
revive (tick ~0) so it sees everything regardless of how long manual repair
takes. Logs only: every time O changes, and every time M==899 (the pulse
moment) - a handful of entries total (~1 per 900 ticks + a few O changes),
not a full per-tick dump. Directly answers: is O ever actually 0 (matching
gate_0's own constant) at the exact tick M hits 899?
"""
OX, OY = 1223.0, 290.0
g0x, g0y = 150.5 + OX, 421.0 + OY

cmd = (
    '/c local surf=game.player.surface; '
    'local f=surf.find_entities_filtered{type="decider-combinator", area={{' + str(g0x-0.7) + ',' + str(g0y-0.7) + '},{' + str(g0x+0.7) + ',' + str(g0y+0.7) + '}}}; '
    'local gate0=f[1]; local log={}; local last_o="init"; local start=game.tick; '
    'script.on_event(defines.events.on_tick, function(event) '
    'local ok,sin=pcall(function() return gate0.get_signals(defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green) end); '
    'local m,o=nil,nil; if ok and sin then for _,s in pairs(sin) do '
    'if s.signal.name=="signal-M" then m=s.count end; if s.signal.name=="signal-O" then o=s.count end end end; '
    'if o~=last_o or m==899 then log[#log+1]={tick=event.tick, m=m, o=o}; last_o=o end; '
    'if event.tick % 1000 == 0 then helpers.write_file("om_log.json", helpers.table_to_json({log=log, tick=event.tick}), false) end '
    'end); '
    'game.print("O/M tracer registered at tick "..start)'
)
with open("om_logger_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
