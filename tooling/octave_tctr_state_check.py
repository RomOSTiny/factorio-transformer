"""
Diagnose fallout from octave_bug_tick_trace_cmd.txt's crash: it destroyed
the old t_ctr and created a fresh one at the same position BEFORE hitting
the bug (self-loop reconnection tried to read the just-destroyed old
entity as its own wire target), so the command aborted mid-loop. Read-only
check of what state the fresh t_ctr is actually in now - which wires (if
any) survived - before writing any repair.
"""
OX, OY = 94.0, -156.0
wx, wy = 0.5 + OX, 1.0 + OY  # t_ctr's local position, unchanged (recreated at oldpos)

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
    'local ok,sigs=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red) end); '
    'rec.out_red={}; if ok and sigs then for _,sg in pairs(sigs) do table.insert(rec.out_red, {name=sg.signal.name, count=sg.count}) end end; '
    'table.insert(out.entities, rec) '
    'end; '
    'helpers.write_file("octave_tctr_state_check.json", helpers.table_to_json(out), false); '
    'game.print("t_ctr state check written, found "..#cands)'
)

with open("octave_tctr_state_check_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes")
