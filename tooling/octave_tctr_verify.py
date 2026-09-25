"""
octave_bug_tick_trace.json shows every watched signal freezing after the
very first tick, and "D"/"s" never appearing at all - consistent with T
being stuck (Factorio omits a computed-zero signal from the network
entirely, and a missing signal reads as 0 in decider comparisons, so a
frozen T<9000 would permanently satisfy read_0's D==0 condition without
ever advancing). Direct read-only check: what is t_ctr's live signal-T
output RIGHT NOW, and what are its actual wire connections (does the
self-loop really exist)?
"""
OX, OY = 94.0, -156.0
wx, wy = 0.5 + OX, 1.0 + OY

cmd = (
    '/c local surf=game.player.surface; '
    f'local wx,wy={wx},{wy}; '
    'local cands=surf.find_entities_filtered{area={{wx-1.3,wy-1.3},{wx+1.3,wy+1.3}}, type="arithmetic-combinator"}; '
    'local out={count=#cands, entities={}}; '
    'for _,e in pairs(cands) do '
    'local rec={unit=e.unit_number, x=e.position.x, y=e.position.y, wires={}}; '
    'for _,cid in pairs({defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, '
    'defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green}) do '
    'local con=e.get_wire_connector(cid,false); '
    'if con then for _,c in pairs(con.connections) do local t=c.target; if t and t.owner and t.owner.valid then '
    'table.insert(rec.wires, {my_cid=cid, to_unit=t.owner.unit_number, to_cid=t.wire_connector_id, to_x=t.owner.position.x, to_y=t.owner.position.y}) '
    'end end end end; '
    'local ok1,in_sigs=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_input_red) end); '
    'rec.in_red={}; if ok1 and in_sigs then for _,sg in pairs(in_sigs) do table.insert(rec.in_red,{name=sg.signal.name,count=sg.count}) end end; '
    'local ok2,out_sigs=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red) end); '
    'rec.out_red={}; if ok2 and out_sigs then for _,sg in pairs(out_sigs) do table.insert(rec.out_red,{name=sg.signal.name,count=sg.count}) end end; '
    'local cb=e.get_control_behavior(); '
    'local ok3,params=pcall(function() return cb.parameters end); '
    'if ok3 and params then rec.params={op=params.operation, fs=params.first_signal and params.first_signal.name, '
    'sc=params.second_constant, ss=params.second_signal and params.second_signal.name, os=params.output_signal and params.output_signal.name} end; '
    'table.insert(out.entities, rec) '
    'end; '
    'helpers.write_file("octave_tctr_verify.json", helpers.table_to_json(out), false); '
    'game.print("t_ctr verify written, found "..#cands)'
)

with open("octave_tctr_verify_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes")
