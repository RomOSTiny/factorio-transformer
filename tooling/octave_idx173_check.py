wx, wy = 73.71360618813776, 999.0861080651041
area = "{{" + str(wx - 2) + "," + str(wy - 2) + "},{" + str(wx + 2) + "," + str(wy + 2) + "}}"
cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}) do '
    'local cb=e.get_control_behavior(); local p=(cb and cb.parameters) or {}; '
    'table.insert(out, {unit=e.unit_number, x=e.position.x, y=e.position.y, '
    'first=(p.first_signal and p.first_signal.name) or "?", op=p.operation or "?", '
    'second=(p.second_signal and p.second_signal.name) or p.second_constant, '
    'outsig=(p.output_signal and p.output_signal.name) or "?"}) end; '
    'helpers.write_file("octave_idx173_check.json", helpers.table_to_json(out), false)'
)
with open("octave_idx173_check_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
