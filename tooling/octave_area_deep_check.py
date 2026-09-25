"""
Wide-area deep check around v_local's expected position - the hard count
mismatch (365 actual vs 366 expected arithmetic-combinators, confirmed with
an honest nearest-match algorithm, not just a greedy-first artifact) proves
v_local is genuinely still missing, and both the entity-repair AND
wire-repair scripts' fuzzy position matching (0.4/0.6 tile tolerance,
matched via bounding-box intersection not exact center distance - found
the hard way checking this exact spot) may have silently attached to a
DIFFERENT nearby combinator instead. Need full ground truth - every
arithmetic-combinator within a few tiles, its exact position, unit_number,
and its wire connections - before doing any targeted fix.
"""
OX, OY = -172.0, 151.0
cx, cy = 245.0 + OX, 298.0 + OY  # 73.0, 449.0
area = "{{" + str(cx - 4) + "," + str(cy - 4) + "},{" + str(cx + 4) + "," + str(cy + 4) + "}}"
cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}) do '
    'local conns={}; '
    'for _,cid in pairs({defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, '
    'defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green}) do '
    'local ok,con=pcall(function() return e.get_wire_connector(cid,false) end); '
    'if ok and con then '
    'local ok2,cs=pcall(function() return con.connections end); '
    'if ok2 and cs then for _,c in pairs(cs) do '
    'local t=c.target; if t and t.owner and t.owner.valid then '
    'table.insert(conns, {from_cid=cid, to_unit=t.owner.unit_number, to_cid=t.wire_connector_id, to_x=t.owner.position.x, to_y=t.owner.position.y}) '
    'end end end end end; '
    'local cb=e.get_control_behavior(); local p=(cb and cb.parameters) or {}; '
    'table.insert(out, {unit=e.unit_number, x=e.position.x, y=e.position.y, '
    'first=(p.first_signal and p.first_signal.name) or "?", op=p.operation or "?", '
    'second=(p.second_signal and p.second_signal.name) or p.second_constant, '
    'outsig=(p.output_signal and p.output_signal.name) or "?", conns=conns}) end; '
    'helpers.write_file("octave_area_deep.json", helpers.table_to_json(out), false)'
)
with open("octave_area_deep_cmd.txt", "w") as f:
    f.write(cmd)
print("bytes:", len(cmd))
