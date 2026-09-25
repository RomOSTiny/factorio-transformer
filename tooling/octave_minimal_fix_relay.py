"""relay_1 missing (expected between relay_0 at world (497.5,497) and
relay_2 at world (503.5,497), evenly spaced -> (500.5,497)). Create it and
rewire relay_0->relay_1->relay_2."""
cmd = (
    '/c local surf=game.player.surface; '
    'local e=surf.create_entity{name="arithmetic-combinator", position={500.5,497}, force=game.player.force}; '
    'local cb=e.get_or_create_control_behavior(); '
    'cb.parameters={first_signal={type="virtual",name="signal-each"}, operation="*", second_constant=1, output_signal={type="virtual",name="signal-each"}}; '
    'local r0=surf.find_entities_filtered{type="arithmetic-combinator", area={{497.0,496.5},{498.0,497.5}}}[1]; '
    'local r2=surf.find_entities_filtered{type="arithmetic-combinator", area={{503.0,496.5},{504.0,497.5}}}[1]; '
    'local c1=r0.get_wire_connector(defines.wire_connector_id.combinator_output_red,true); '
    'local c2=e.get_wire_connector(defines.wire_connector_id.combinator_input_red,true); '
    'c1.connect_to(c2,false,defines.wire_origin.script); '
    'local c3=e.get_wire_connector(defines.wire_connector_id.combinator_output_red,true); '
    'local c4=r2.get_wire_connector(defines.wire_connector_id.combinator_input_red,true); '
    'c3.connect_to(c4,false,defines.wire_origin.script); '
    'helpers.write_file("octave_minimal_fix.json", helpers.table_to_json({created=e.valid, r0_found=r0~=nil, r2_found=r2~=nil}), false)'
)
with open("octave_minimal_fix_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
