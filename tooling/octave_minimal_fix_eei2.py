cmd = (
    '/c local surf=game.player.surface; '
    'local eei=surf.find_entities_filtered{type="electric-energy-interface", area={{490.5,596.5},{491.5,597.5}}}[1]; '
    'local pole=surf.find_entities_filtered{type="electric-pole", area={{500.0,597.0},{501.0,598.0}}}[1]; '
    'local ok1,c1=pcall(function() return eei.get_wire_connector(defines.wire_connector_id.pole_copper,true) end); '
    'local ok2,c2=pcall(function() return pole.get_wire_connector(defines.wire_connector_id.pole_copper,true) end); '
    'local err3="none"; local ok3=false; '
    'if ok1 and ok2 then ok3,err3=pcall(function() c1.connect_to(c2,false,defines.wire_origin.script) end); end '
    'helpers.write_file("octave_minimal_fix_eei2.json", helpers.table_to_json({c1_ok=ok1, c1_err=(not ok1 and tostring(c1)) or "ok", c2_ok=ok2, c2_err=(not ok2 and tostring(c2)) or "ok", connect_ok=ok3, connect_err=tostring(err3)}), false)'
)
with open("octave_minimal_fix_eei2_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
