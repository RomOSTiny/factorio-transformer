points = [
    ("eei", 491.0, 597.0, "electric-energy-interface"),
    ("pole0", 500.5, 597.5, "electric-pole"),
    ("pole1", 500.5, 600.5, "electric-pole"),
    ("pole2", 500.5, 603.5, "electric-pole"),
    ("relay_0", 497.5, 597.0, "arithmetic-combinator"),
    ("o_collect", 509.5, 600.0, "arithmetic-combinator"),
]
parts = ["/c local surf=game.player.surface; local out={}; "]
for name, x, y, etype in points:
    area = "{{" + str(x - 0.5) + "," + str(y - 0.5) + "},{" + str(x + 0.5) + "," + str(y + 0.5) + "}}"
    parts.append(
        'local e_' + name + '=surf.find_entities_filtered{type="' + etype + '", area=' + area + '}[1]; '
        'if e_' + name + ' then '
        'local ok,ec=pcall(function() return e_' + name + '.electric_network_id end); '
        'local ok2,es=pcall(function() return e_' + name + '.energy end); '
        'local cb = e_' + name + '.get_control_behavior and e_' + name + '.get_control_behavior(); '
        'local p=(cb and cb.parameters); '
        'out["' + name + '"]={found=true, net=(ok and ec) or "none", energy=(ok2 and es) or -1, '
        'first=(p and p.first_signal and p.first_signal.name) or "n/a", op=(p and p.operation) or "n/a", outsig=(p and p.output_signal and p.output_signal.name) or "n/a"}; '
        'else out["' + name + '"]={found=false}; end; '
    )
parts.append('helpers.write_file("octave_minimal_power2.json", helpers.table_to_json(out), false)')
cmd = "".join(parts)
with open("octave_minimal_power_check2_cmd.txt", "w") as f:
    f.write(cmd)
print("bytes:", len(cmd))
