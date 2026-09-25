"""
Per-firing tick log for the octave test's 6 gates - same decisive technique
that resolved the matmul block's timing bugs (build_gate_logger_cmd.py/
analyze_gate_log.py, Reshenie 26): register a persistent on_tick handler
that records (gate, tick, o, s) every time a gate's output actually changes,
instead of only ever inspecting the frozen aftermath. The final_check dump
showed o=0 for every single test case (even ones expecting o=7,8,19,30) and
s values that are suspicious round multiples of the expected s (62=2*31,
216=8*27, 464=16*29) - a per-tick log will show whether this is a real
math bug in the octave/subbucket circuit itself, or a repeat of the
"private data merged onto a shared broadcast network" class of bug
(Reshenie 14), or something else entirely.
"""
OX, OY = 178.0, -199.0  # measured live: tctr_pos (178.5,-198) - local (0.5,1.0)

ACC_X, ACC_Y = 250, 400  # from stage2_octave_isolated_test.py
SLOT_W2 = 8
N_TEST = 6
positions = [(ACC_X + i * SLOT_W2 + 0.5, ACC_Y + 1.0) for i in range(N_TEST)]
o_collect_pos = (250 - 15 + 0.5, 0 + 3.0)  # CMP_X-15+0.5, CMP_Y+3.0 - matches the
# collector redesign's moved o_collect position, NOT the original far-right
# spot this constant was hardcoded to before (found found=0 in-game because
# of exactly this staleness - the file's own top-of-session warning about
# hardcoded positions applies to itself here).
s_pos = (250 + 0.5, 300 + 4.0)

parts = ['/c local surf=game.player.surface; local gates={}; ']
for i, (lx, ly) in enumerate(positions):
    wx, wy = lx + OX, ly + OY
    parts.append(f'gates[{i}]=surf.find_entities_filtered{{type="decider-combinator", area={{{{{wx-0.7},{wy-0.7}}},{{{wx+0.7},{wy+0.7}}}}}}}[1]; ')
owx, owy = o_collect_pos[0] + OX, o_collect_pos[1] + OY
swx, swy = s_pos[0] + OX, s_pos[1] + OY
parts.append(f'local ocol=surf.find_entities_filtered{{type="arithmetic-combinator", area={{{{{owx-0.7},{owy-0.7}}},{{{owx+0.7},{owy+0.7}}}}}}}[1]; ')
parts.append(f'local se=surf.find_entities_filtered{{type="arithmetic-combinator", area={{{{{swx-0.7},{swy-0.7}}},{{{swx+0.7},{swy+0.7}}}}}}}[1]; ')
parts.append(
    'local found=0; for i=0,5 do if gates[i] then found=found+1 end end; '
    'local log={}; local ocol_log={}; local last_o=nil; local se_log={}; local last_s=nil; '
    'script.on_event(defines.events.on_tick, function(event) '
    'for i=0,5 do local e=gates[i]; if e and e.valid then '
    'local ok,sout=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'if ok and sout then local o,s=nil,nil; for _,sg in pairs(sout) do '
    'if sg.signal.name=="signal-O" then o=sg.count end; if sg.signal.name=="signal-S" then s=sg.count end end; '
    'if o~=nil or s~=nil then log[#log+1]={gate=i,tick=event.tick,o=o,s=s} end end '
    'end end '
    'if ocol and ocol.valid then '
    'local ok2,sout2=pcall(function() return ocol.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local cur=nil; if ok2 and sout2 then for _,s in pairs(sout2) do if s.signal.name=="signal-O" then cur=s.count end end end; '
    'if cur~=last_o then ocol_log[#ocol_log+1]={tick=event.tick,o=cur}; last_o=cur; '
    'if #ocol_log>200 then table.remove(ocol_log,1) end end end; '
    'if se and se.valid then '
    'local ok3,sout3=pcall(function() return se.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local cur2=nil; if ok3 and sout3 then for _,s in pairs(sout3) do if s.signal.name=="signal-S" then cur2=s.count end end end; '
    'if cur2~=last_s then se_log[#se_log+1]={tick=event.tick,s=cur2}; last_s=cur2; '
    'if #se_log>200 then table.remove(se_log,1) end end end; '
    'if event.tick % 500 == 0 then '
    'helpers.write_file("octave_gate_fire_log.json", helpers.table_to_json({log=log, ocol_log=ocol_log, se_log=se_log, found=found, tick=event.tick}), false) '
    'end end); '
    'helpers.write_file("octave_gate_fire_log.json", helpers.table_to_json({log=log, ocol_log=ocol_log, se_log=se_log, found=found, tick=game.tick}), false); '
    'game.print("octave gate logger registered, gates found: "..found)'
)
cmd = "".join(parts)
with open("octave_gate_logger_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd), "bytes")
