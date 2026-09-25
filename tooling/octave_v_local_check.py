OX, OY = -172.0, 151.0
wx, wy = 245.0 + OX, 298.0 + OY
area = "{{" + str(wx - 0.6) + "," + str(wy - 0.6) + "},{" + str(wx + 0.6) + "," + str(wy + 0.6) + "}}"
cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do '
    'table.insert(out, {name=e.name, x=e.position.x, y=e.position.y, unit=e.unit_number}) end; '
    'helpers.write_file("octave_v_local_check.json", helpers.table_to_json(out), false)'
)
with open("octave_v_local_check_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
