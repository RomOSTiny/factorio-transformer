points = [
    ("relay_0", 497.5, 597.0, "arithmetic-combinator"),
    ("relay_2", 503.5, 597.0, "arithmetic-combinator"),
    ("cmp_0", 506.5, 597.0, "decider-combinator"),
    ("collect_0", 506.5, 600.0, "arithmetic-combinator"),
    ("o_collect", 509.5, 600.0, "arithmetic-combinator"),
]
parts = ["/c local surf=game.player.surface; local out={}; "]
for name, x, y, etype in points:
    area = "{{" + str(x - 0.5) + "," + str(y - 0.5) + "},{" + str(x + 0.5) + "," + str(y + 0.5) + "}}"
    parts.append(
        'local e_' + name + '=surf.find_entities_filtered{type="' + etype + '", area=' + area + '}[1]; '
        'if e_' + name + ' then '
        'local ok1,sin=pcall(function() return e_' + name + '.get_signals(defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green) end); '
        'local ok2,sout=pcall(function() return e_' + name + '.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
        'local ivals={}; if ok1 and sin then for _,s in pairs(sin) do table.insert(ivals,{name=s.signal.name,count=s.count}) end end; '
        'local ovals={}; if ok2 and sout then for _,s in pairs(sout) do table.insert(ovals,{name=s.signal.name,count=s.count}) end end; '
        'out["' + name + '"]={found=true, input=ivals, output=ovals}; '
        'else out["' + name + '"]={found=false}; end; '
    )
parts.append('helpers.write_file("octave_minimal_trace2.json", helpers.table_to_json(out), false)')
cmd = "".join(parts)
with open("octave_minimal_trace2_cmd.txt", "w") as f:
    f.write(cmd)
print("bytes:", len(cmd))
