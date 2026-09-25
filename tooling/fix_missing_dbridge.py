exec(open("build_display_bridge.py").read().split("BATCH_SIZE = 15")[0])

missing_idx = [4, 9, 14, 19, 22, 27, 28, 33]
missing = [hops[i - 1] for i in missing_idx]
for m in missing:
    print(m)

parts = ['/c local surf=game.player.surface; local force=game.player.force; local created,failed=0,0; ']
for hid, x, y in missing:
    parts.append(
        f'do local ent=surf.create_entity{{name="arithmetic-combinator",position={{{x},{y}}},force=force,raise_built=false}}; '
        f'if ent then ent.get_or_create_control_behavior().parameters={{operation="*",first_signal={{name="signal-each",type="virtual"}},second_constant=1,output_signal={{name="signal-each",type="virtual"}}}}; created=created+1 else failed=failed+1 end end; '
    )
parts.append('game.print("missing dbridge fix: created="..created..", failed="..failed)')
cmd = "".join(parts)
with open("fix_missing_dbridge.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd))
