exec(open("build_letter_input_power.py").read().split("cmd = build_lua()")[0])

parts = ['/c local surf=game.player.surface; local missing={}; ']
for sid, x, y in new_subs:
    parts.append(
        f'if not surf.find_entities_filtered{{name="substation",position={{{x},{y}}},radius=0.2}}[1] then '
        f'missing[#missing+1]="{sid} ({x},{y})" end; '
    )
parts.append('game.print("missing count: "..#missing); for _,m in pairs(missing) do game.print(m) end')
cmd = "".join(parts)
with open("lin_sub_verify.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "chars,", len(new_subs), "to check")
