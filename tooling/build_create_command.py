import json


def lua_sig(pair):
    if pair is None:
        return "nil"
    return '{name="%s",type="%s"}' % (pair["name"], pair["type"])


def lua_str(s):
    return '"%s"' % s


manifest = json.load(open("entity_repair_manifest.json", encoding="utf-8"))

creates = []
for i, e in enumerate(manifest):
    var = f"e{i}"
    creates.append(
        f'local {var}=surf.create_entity{{name={lua_str(e["name"])},position={{{e["x"]},{e["y"]}}},force=force,raise_built=false}}; '
        f"created=created+1; "
    )
    if e["name"] == "arithmetic-combinator":
        parts = [f'operation={lua_str(e["op"])}']
        if "fo_const" in e:
            parts.append(f'first_constant={e["fo_const"]}')
        else:
            parts.append(f'first_signal={lua_sig(e["fo_sig"])}')
        if "so_const" in e:
            parts.append(f'second_constant={e["so_const"]}')
        else:
            parts.append(f'second_signal={lua_sig(e["so_sig"])}')
        parts.append(f'output_signal={lua_sig(e["out"])}')
        creates.append(f'{var}.get_or_create_control_behavior().parameters={{{",".join(parts)}}}; ')
    elif e["name"] == "decider-combinator":
        conds = []
        for c in e["conditions"]:
            cparts = [f'first_signal={lua_sig(c["fs"])}', f'comparator={lua_str(c["cmp"])}', f'compare_type={lua_str(c["ct"])}']
            if "ss" in c:
                cparts.append(f'second_signal={lua_sig(c["ss"])}')
            else:
                cparts.append(f'constant={c["const"]}')
            conds.append("{" + ",".join(cparts) + "}")
        outs = []
        for o in e["outputs"]:
            outs.append(f'{{signal={lua_sig(o["sig"])},copy_count_from_input={"true" if o["copy"] else "false"},constant={o["const"]}}}')
        creates.append(f'{var}.get_or_create_control_behavior().parameters={{conditions={{{",".join(conds)}}},outputs={{{",".join(outs)}}}}}; ')

body = "".join(creates)
command = (
    "/c local surf=game.player.surface; local force=game.player.force; local created=0; "
    + body
    + 'game.print("created "..created.." entities")'
)

with open("create_missing_entities_command.txt", "w", encoding="utf-8") as f:
    f.write(command)

print(f"Command length: {len(command)} chars")
print(f"Entities to create: {len(manifest)}")

# also split into smaller batches in case the console has a length limit
BATCH_SIZE = 15
n_batches = (len(creates) // 2 + BATCH_SIZE - 1) // BATCH_SIZE  # creates has 2 entries per entity typically (create+configure), but count varies - just chunk manifest instead
chunk_starts = list(range(0, len(manifest), BATCH_SIZE))
idx = 0
entity_creates = []
cur = []
count_in_cur = 0
# rebuild creates grouped strictly per-entity (each entity contributed 2 strings to `creates`: the create line and the configure line)
per_entity = []
i = 0
ci = 0
while ci < len(creates):
    # each entity always emits exactly 2 lines (create_entity + control_behavior)
    per_entity.append(creates[ci] + creates[ci + 1])
    ci += 2

for b, start in enumerate(chunk_starts):
    chunk = per_entity[start : start + BATCH_SIZE]
    batch_command = (
        "/c local surf=game.player.surface; local force=game.player.force; local created=0; "
        + "".join(chunk)
        + f'game.print("batch {b+1}/{len(chunk_starts)}: created "..created.." entities")'
    )
    with open(f"create_batch_{b+1}.txt", "w", encoding="utf-8") as f:
        f.write(batch_command)
    print(f"batch {b+1}: {len(batch_command)} chars, {len(chunk)} entities")
