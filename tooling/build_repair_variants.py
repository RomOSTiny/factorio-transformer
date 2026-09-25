"""
Builds repair Lua from the already-saved repair_300_manifest.json (no
draftsman reload needed - that manifest already has fully-resolved
parameters). Produces three variants to try in order:
  1. One single command, all 1306 entities, each wrapped in pcall (so one
     bad create doesn't lose the rest) - try this first.
  2. Batches of 300 (fallback if #1's console input chokes/truncates).
  3. Batches of 100 (fallback if even #2 is too much).
Every create is wrapped in pcall regardless of batch size, same robustness
idea as the ghost-revive fix - a single failure shouldn't lose an entire
batch's worth of work.
"""

import json
import math

manifest = json.load(open("repair_300_manifest.json", encoding="utf-8"))
print(f"Entities to repair: {len(manifest)}")


def lua_sig(pair):
    if pair is None:
        return "nil"
    return '{name="%s",type="%s"}' % (pair["name"], pair["type"])


def lua_str(s):
    return '"%s"' % s


def entity_lua(e):
    parts = [f'surf.create_entity{{name={lua_str(e["name"])},position={{{e["x"]},{e["y"]}}},force=force,raise_built=false}}']
    create_expr = parts[0]
    body = []
    if e["name"] == "arithmetic-combinator":
        aparts = [f'operation={lua_str(e["op"])}']
        if "fo_const" in e:
            aparts.append(f'first_constant={e["fo_const"]}')
        else:
            aparts.append(f'first_signal={lua_sig(e["fo_sig"])}')
        if "so_const" in e:
            aparts.append(f'second_constant={e["so_const"]}')
        else:
            aparts.append(f'second_signal={lua_sig(e["so_sig"])}')
        aparts.append(f'output_signal={lua_sig(e["out"])}')
        body.append(f'ee.get_or_create_control_behavior().parameters={{{",".join(aparts)}}}')
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
        body.append(f'ee.get_or_create_control_behavior().parameters={{conditions={{{",".join(conds)}}},outputs={{{",".join(outs)}}}}}')
    elif e["name"] == "constant-combinator":
        sig_entries = []
        for i, s_ in enumerate(e["signals"]):
            if s_["name"] is None:
                continue
            sig_entries.append(f'{{index={i+1},signal={{name="{s_["name"]}",type="virtual"}},count={s_["count"]}}}')
        body.append(f'ee.get_or_create_control_behavior().parameters={{{",".join(sig_entries)}}}')
    inner = f"local ee={create_expr}; " + "; ".join(body)
    # pcall around the WHOLE per-entity block (create + configure) - if
    # create_entity itself fails (e.g. still-colliding spot), configure is
    # never reached either, and the failure is caught and counted, not
    # left to crash the rest of the batch/command. pcall's own return
    # value IS the success flag - no need for a separate one.
    return f'if pcall(function() {inner} end) then created=created+1 else failed=failed+1 end; '


per_entity = [entity_lua(e) for e in manifest]

HEADER = "local surf=game.player.surface; local force=game.player.force; local created=0; local failed=0; "


def make_command(chunk, label):
    return "/c " + HEADER + "".join(chunk) + f'game.print("{label}: created "..created..", failed "..failed)'


# ---- variant 1: everything in one command ----
all_command = make_command(per_entity, "repair ALL")
with open("repair_all_in_one.txt", "w", encoding="utf-8") as f:
    f.write(all_command)
print(f"repair_all_in_one.txt: {len(all_command)} chars")

# ---- variant 2 & 3: fixed-count batches ----
for batch_size, tag in ((300, "300"), (100, "100")):
    n_batches = math.ceil(len(per_entity) / batch_size)
    sizes = []
    for b in range(n_batches):
        chunk = per_entity[b * batch_size : (b + 1) * batch_size]
        cmd = make_command(chunk, f"repair batch {b+1}/{n_batches}")
        with open(f"repair_{tag}_batch_{b+1}.txt", "w", encoding="utf-8") as f:
            f.write(cmd)
        sizes.append(len(cmd))
    print(f"batch size {tag}: {n_batches} batches, sizes {min(sizes)}-{max(sizes)} chars")
