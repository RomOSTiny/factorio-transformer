OX, OY = -172.0, 151.0
wx, wy = 245.0 + OX, 298.0 + OY  # exactly what octave_repair_cmd.py's repair_entities_cmd computes
# exact same box the repair script itself uses: +-0.4
area = "{{" + str(wx - 0.4) + "," + str(wy - 0.4) + "},{" + str(wx + 0.4) + "," + str(wy + 0.4) + "}}"
cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}) do '
    'table.insert(out, {name=e.name, x=e.position.x, y=e.position.y, unit=e.unit_number}) end; '
    'helpers.write_file("octave_v_local_check2.json", helpers.table_to_json(out), false)'
)
with open("octave_v_local_check2_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
