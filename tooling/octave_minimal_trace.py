points = [
    ("src", 494.5, 496.5, "constant-combinator"),
    ("relay_0", 497.5, 497.0, "arithmetic-combinator"),
    ("relay_1", 500.5, 497.0, "arithmetic-combinator"),
    ("relay_2", 503.5, 497.0, "arithmetic-combinator"),
]
parts = ["/c local surf=game.player.surface; local out={}; "]
for name, x, y, etype in points:
    area = "{{" + str(x - 0.5) + "," + str(y - 0.5) + "},{" + str(x + 0.5) + "," + str(y + 0.5) + "}}"
    parts.append(
        'local e_' + name + '=surf.find_entities_filtered{type="' + etype + '", area=' + area + '}[1]; '
        'if e_' + name + ' then '
        'local ok,sout=pcall(function() return e_' + name + '.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
        'local vals={}; if ok and sout then for _,s in pairs(sout) do table.insert(vals,{name=s.signal.name,count=s.count}) end end; '
        'out["' + name + '"]={found=true, x=e_' + name + '.position.x, y=e_' + name + '.position.y, out=vals}; '
        'else out["' + name + '"]={found=false}; end; '
    )
parts.append('helpers.write_file("octave_minimal_trace.json", helpers.table_to_json(out), false)')
cmd = "".join(parts)
with open("octave_minimal_trace_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
