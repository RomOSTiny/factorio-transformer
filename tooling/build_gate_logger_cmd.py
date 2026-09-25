"""
Persistent on_tick logger (same technique as Reshenie 25's original diagnosis)
- registered as early as possible after revive, BEFORE repair, so it sees
the whole sweep regardless of how long manual repair takes. Logs every real
firing (output becomes non-empty) of every gate_j, with the exact signal-P
value gated through - lets us directly verify, after the fact, whether each
gate fired exactly 5 times with the values expected from the reference
weights/inputs, instead of only ever inspecting the frozen aftermath.
"""
OX, OY = -1577.0, -1710.0  # measured live: tctr_pos (-1576.5,-1709) - local (0.5,1.0)
assert OX is not None

ACC_X, ACC_Y = 150, 420  # ALU_X, ALU_Y+20 from stage2_matmul_test_export.py
SLOT_W = 8
positions = []
for j in range(12):
    gx = ACC_X + j * SLOT_W
    positions.append((gx + 0.5, ACC_Y + 1.0))
mult_pos = (150.5, 404.0)

parts = ['/c local surf=game.player.surface; local gates={}; ']
for j, (lx, ly) in enumerate(positions):
    wx, wy = lx + OX, ly + OY
    parts.append(f'gates[{j}]=surf.find_entities_filtered{{type="decider-combinator", area={{{{{wx-0.7},{wy-0.7}}},{{{wx+0.7},{wy+0.7}}}}}}}[1]; ')
mwx, mwy = mult_pos[0] + OX, mult_pos[1] + OY
parts.append(f'local mult=surf.find_entities_filtered{{type="arithmetic-combinator", area={{{{{mwx-0.7},{mwy-0.7}}},{{{mwx+0.7},{mwy+0.7}}}}}}}[1]; ')
parts.append(
    'local found=0; for j=0,11 do if gates[j] then found=found+1 end end; '
    'local log={}; local mult_log={}; local last_mult=nil; '
    'script.on_event(defines.events.on_tick, function(event) '
    'for j=0,11 do local e=gates[j]; if e and e.valid then '
    'local ok,sout=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'if ok and sout then for _,s in pairs(sout) do if s.signal.name=="signal-P" then log[#log+1]={gate=j,tick=event.tick,p=s.count} end end end '
    'end end '
    'if mult and mult.valid then '
    'local ok2,sout2=pcall(function() return mult.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local cur=nil; if ok2 and sout2 then for _,s in pairs(sout2) do if s.signal.name=="signal-P" then cur=s.count end end end; '
    'if cur~=last_mult then mult_log[#mult_log+1]={tick=event.tick,p=cur}; last_mult=cur; '
    'if #mult_log>400 then table.remove(mult_log,1) end end end; '
    'if event.tick % 500 == 0 then '
    'helpers.write_file("gate_fire_log.json", helpers.table_to_json({log=log, mult_log=mult_log, found=found, tick=event.tick}), false) '
    'end end); '
    'helpers.write_file("gate_fire_log.json", helpers.table_to_json({log=log, mult_log=mult_log, found=found, tick=game.tick}), false); '
    'game.print("gate logger registered, gates found: "..found)'
)
cmd = "".join(parts)
with open("gate_logger_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd), "bytes")
