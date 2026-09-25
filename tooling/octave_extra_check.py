pts = [(172.5, 146), (147.5, 185), (117.5, 230), (79.5, 288), (110.5, 409), (79.5, 540)]
parts = ['/c local surf=game.player.surface; local out={}; ']
for i, (x, y) in enumerate(pts):
    parts.append(
        f'local es{i}=surf.find_entities_filtered{{type="arithmetic-combinator", area={{{{{x-0.5},{y-0.5}}},{{{x+0.5},{y+0.5}}}}}}}; '
        f'for _,e in pairs(es{i}) do local cb=e.get_control_behavior(); local p=(cb and cb.parameters) or {{}}; '
        f'table.insert(out, {{unit=e.unit_number, x=e.position.x, y=e.position.y, '
        f'first=(p.first_signal and p.first_signal.name) or "NIL", op=p.operation or "NIL", '
        f'outsig=(p.output_signal and p.output_signal.name) or "NIL"}}) end; '
    )
parts.append('helpers.write_file("octave_extra_check.json", helpers.table_to_json(out), false)')
cmd = "".join(parts)
with open("octave_extra_check_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
