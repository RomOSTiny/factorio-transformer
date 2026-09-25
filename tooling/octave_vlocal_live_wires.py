wx, wy = 73.5, 999.0  # v_local's live position, confirmed by earlier queries
area = "{{" + str(wx - 0.6) + "," + str(wy - 0.6) + "},{" + str(wx + 0.6) + "," + str(wy + 0.6) + "}}"
cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'local e=surf.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}[1]; '
    'if e then '
    'for _,cid in pairs({defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, '
    'defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green}) do '
    'local ok,con=pcall(function() return e.get_wire_connector(cid,false) end); '
    'if ok and con then local ok2,cs=pcall(function() return con.connections end); '
    'if ok2 and cs then for _,c in pairs(cs) do local t=c.target; if t and t.owner and t.owner.valid then '
    'table.insert(out, {my_cid=cid, to_unit=t.owner.unit_number, to_cid=t.wire_connector_id, to_x=t.owner.position.x, to_y=t.owner.position.y}) '
    'end end end end end end; '
    'helpers.write_file("octave_vlocal_live_wires.json", helpers.table_to_json(out), false)'
)
with open("octave_vlocal_live_wires_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
