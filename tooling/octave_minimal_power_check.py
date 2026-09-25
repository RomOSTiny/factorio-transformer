points = [
    ("src", 494.5, 596.5),
    ("relay_0", 497.5, 597.0),
    ("cmp_0", 506.5, 597.0),
    ("o_collect", 509.5, 600.0),
]
parts = ["/c local surf=game.player.surface; local out={}; "]
for name, x, y in points:
    area = "{{" + str(x - 0.5) + "," + str(y - 0.5) + "},{" + str(x + 0.5) + "," + str(y + 0.5) + "}}"
    parts.append(
        'local e_' + name + '=surf.find_entities_filtered{area=' + area + '}[1]; '
        'if e_' + name + ' then '
        'local ok,ec=pcall(function() return e_' + name + '.electric_network_id end); '
        'local ok2,es=pcall(function() return e_' + name + '.energy end); '
        'out["' + name + '"]={found=true, name=e_' + name + '.name, net=(ok and ec) or "none", energy=(ok2 and es) or -1}; '
        'else out["' + name + '"]={found=false}; end; '
    )
parts.append('helpers.write_file("octave_minimal_power.json", helpers.table_to_json(out), false)')
cmd = "".join(parts)
with open("octave_minimal_power_check_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
