OX, OY = 423.0, 1690.0
g0x, g0y = 150.5 + OX, 421.0 + OY

cmd = (
    '/c local surf=game.player.surface; '
    'local f=surf.find_entities_filtered{type="decider-combinator", area={{' + str(g0x-0.7) + ',' + str(g0y-0.7) + '},{' + str(g0x+0.7) + ',' + str(g0y+0.7) + '}}}; '
    'local gate0=f[1]; local log={}; local last_m=nil; local start=game.tick; '
    'script.on_event(defines.events.on_tick, function(event) '
    'if event.tick-start>1000 then return end; '
    'local ok,sin=pcall(function() return gate0.get_signals(defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green) end); '
    'local m,o=nil,nil; if ok and sin then for _,s in pairs(sin) do '
    'if s.signal.name=="signal-M" then m=s.count end; if s.signal.name=="signal-O" then o=s.count end end end; '
    'if m~=last_m then log[#log+1]={tick=event.tick, m=m, o=o}; last_m=m end; '
    'if event.tick-start==1000 then helpers.write_file("pulse_watch.json", helpers.table_to_json(log), false) end '
    'end); '
    'game.print("pulse watch registered at tick "..start)'
)
with open("pulse_watch_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
