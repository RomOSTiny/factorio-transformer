exec(open("build_letter_input_power.py").read().split("cmd = build_lua()")[0])

parts = ['/c local out={}; ']
for sid, x, y in new_subs:
    parts.append(
        f'do local e=game.player.surface.find_entities_filtered{{name="substation",position={{{x},{y}}},radius=1}}[1]; '
        f'out[#out+1]={{id="{sid}",planned_x={x},planned_y={y},found=(e~=nil),real_x=(e and e.position.x or nil),real_y=(e and e.position.y or nil)}} end; '
    )
parts.append('helpers.write_file("lin_sub_status.json", helpers.table_to_json(out), false); game.print("wrote lin_sub_status.json")')
cmd = "".join(parts)
with open("lin_sub_verify_file.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "chars")
