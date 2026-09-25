OX, OY = 423.0, 990.0
tctr_x, tctr_y = 0.5 + OX, 1.0 + OY
cmd = (
    '/c local surf=game.player.surface; '
    'local f=surf.find_entities_filtered{type="arithmetic-combinator", area={{' + str(tctr_x-0.7) + ',' + str(tctr_y-0.7) + '},{' + str(tctr_x+0.7) + ',' + str(tctr_y+0.7) + '}}}; '
    'local t="?"; if #f>0 then local ok,sig=pcall(function() return f[1].get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'if ok and sig then for _,s in pairs(sig) do if s.signal.name=="signal-T" then t=s.count end end end end; '
    'helpers.write_file("tick_check.json", helpers.table_to_json({t_ctr=t, game_tick=game.tick}), false)'
)
with open("tick_check_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
