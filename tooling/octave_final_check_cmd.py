"""
Final check for the octave/subbucket isolated test: after the sweep settles
(K=300, N_TEST=6 -> 1800 ticks, ~30s), dump acc_o_i (signal-A) and acc_s_i
(signal-B) for all 6 test cases and compare to EXPECTED from
stage2_octave_isolated_test.py. acc_o_i/acc_s_i are safe to read via
get_signals - both have a real outgoing connection (their own self-loop),
unlike a true terminal node with no consumer at all (Reshenie 5/26's
get_signals trap only applies when there's NO wire on that side).
Fill in OX, OY from octave_revive.json's tctr_pos (x-0.5, y-1.0) before
running.
"""
OX, OY = -172.0, 151.0  # measured live: tctr_pos (-171.5,152) - local (0.5,1.0)
assert OX is not None and OY is not None, "set OX, OY from octave_revive.json tctr_pos first"

ACC_X, ACC_Y = 250, 400  # from stage2_octave_isolated_test.py
SLOT_W2 = 8
N_TEST = 6

parts = ['/c local surf=game.player.surface; local out={}; ']
for i in range(N_TEST):
    gx = ACC_X + i * SLOT_W2
    ax_o, ay_o = gx + 2.5 + OX, ACC_Y + 1.0 + OY
    ax_s, ay_s = gx + 4.5 + OX, ACC_Y + 1.0 + OY
    parts.append(
        f'local eo=surf.find_entities_filtered{{type="arithmetic-combinator", area={{{{{ax_o - 0.4},{ay_o - 0.4}}},{{{ax_o + 0.4},{ay_o + 0.4}}}}}}}[1]; '
        f'local es=surf.find_entities_filtered{{type="arithmetic-combinator", area={{{{{ax_s - 0.4},{ay_s - 0.4}}},{{{ax_s + 0.4},{ay_s + 0.4}}}}}}}[1]; '
        f'local vo,vs=0,0; '
        f'if eo then local ok,sig=pcall(function() return eo.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
        f'if ok and sig then for _,s in pairs(sig) do if s.signal.name=="signal-A" then vo=s.count end end end end; '
        f'if es then local ok,sig=pcall(function() return es.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
        f'if ok and sig then for _,s in pairs(sig) do if s.signal.name=="signal-B" then vs=s.count end end end end; '
        f'out[{i + 1}]={{i={i}, o=vo, s=vs, found_o=(eo~=nil), found_s=(es~=nil)}}; '
    )
parts.append('helpers.write_file("octave_final_check.json", helpers.table_to_json(out), false)')
cmd = "".join(parts)
with open("octave_final_check_cmd.txt", "w") as f:
    f.write(cmd)
print("bytes:", len(cmd))
