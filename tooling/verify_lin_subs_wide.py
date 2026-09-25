exec(open("build_letter_input_power.py").read().split("cmd = build_lua()")[0])

# use the ORIGINAL (pre-fix) uncorrected positions too, since the first
# creation attempt used those - check both the old .5-offset spots and the
# corrected integer spots, radius 1 tile, to find out what's REALLY there
# before creating anything new (avoid duplicating any that DID land, just
# snapped, from the original 39-substation attempt)
parts = ['/c local surf=game.player.surface; local found={}; local missing={}; ']
for sid, x, y in new_subs:
    parts.append(
        f'local e=surf.find_entities_filtered{{name="substation",position={{{x},{y}}},radius=1}}[1]; '
        f'if e then found[#found+1]="{sid} -> ("..e.position.x..","..e.position.y..")" else missing[#missing+1]="{sid} planned=({x},{y})" end; '
    )
parts.append('game.print("found: "..#found..", missing: "..#missing); for _,f in pairs(found) do game.print("FOUND "..f) end; for _,m in pairs(missing) do game.print("MISSING "..m) end')
cmd = "".join(parts)
with open("lin_sub_verify_wide.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "chars")
