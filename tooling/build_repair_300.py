"""
Builds Lua repair batches for the 1306 combinators that census_300.py found
missing from the in-game build (see census_300_missing.json).

Loads export_full_300syl.txt via Blueprint.from_string() - NOT by
re-running export_full.py's generation (25-30 min) - this only parses the
already-generated blueprint string (~5 min, still slow due to draftsman's
per-entity attrs/cattrs validation, but far cheaper than regenerating).
Parsing through draftsman (rather than hand-decoding the raw JSON and
guessing at Factorio's default values, e.g. arithmetic operation="*") means
every field is resolved exactly the way the game itself would resolve it -
no risk of a silently-wrong default sneaking into a repaired entity.
"""

import json
import math
import time

from draftsman.classes.blueprint import Blueprint

BP_FILE = "export_full_300syl.txt"
MISSING_FILE = "census_300_missing.json"

t0 = time.time()
with open(BP_FILE) as f:
    s = f.read()
bp = Blueprint.from_string(s)
print(f"Loaded {len(bp.entities)} entities in {time.time()-t0:.0f}s")

missing = json.load(open(MISSING_FILE, encoding="utf-8"))
print(f"Missing entries to repair: {len(missing)}")

COMPARATOR_MAP = {"≥": ">=", "≤": "<=", "≠": "!=", "=": "=", ">": ">", "<": "<"}


def norm_cmp(c):
    return COMPARATOR_MAP.get(c, c)


def sig_pair(sig):
    if sig is None:
        return None
    if hasattr(sig, "name"):
        return {"name": sig.name, "type": getattr(sig, "type", None) or "item"}
    if isinstance(sig, dict):
        return {"name": sig.get("name"), "type": sig.get("type", "item")}
    return {"name": sig, "type": "item"}


def sig_name(sig):
    p = sig_pair(sig)
    return p["name"] if p else None


manifest = []
for m in missing:
    idx = m["entity_number"] - 1  # blueprint entity_number is 1-indexed array position
    e = bp.entities[idx]
    assert e.name == m["name"], f"mismatch at {idx}: expected {m['name']}, got {e.name}"
    entry = {"name": e.name, "x": m["x"], "y": m["y"]}
    if e.name == "arithmetic-combinator":
        entry["op"] = e.operation
        entry["out"] = sig_pair(e.output_signal)
        fo, so = e.first_operand, e.second_operand
        if isinstance(fo, (int, float)):
            entry["fo_const"] = fo
        else:
            entry["fo_sig"] = sig_pair(fo)
        if isinstance(so, (int, float)):
            entry["so_const"] = so
        else:
            entry["so_sig"] = sig_pair(so)
    elif e.name == "decider-combinator":
        conds = []
        for c in e.conditions:
            cond = {"cmp": norm_cmp(c.comparator), "ct": c.compare_type}
            cond["fs"] = sig_pair(c.first_signal)
            if c.second_signal is not None:
                cond["ss"] = sig_pair(c.second_signal)
            else:
                cond["const"] = c.constant
            conds.append(cond)
        outs = []
        for o in e.outputs:
            outs.append({"sig": sig_pair(o.signal), "copy": bool(o.copy_count_from_input), "const": o.constant if o.constant is not None else 0})
        entry["conditions"] = conds
        entry["outputs"] = outs
    elif e.name == "constant-combinator":
        sigs = []
        for s_ in e.signals:
            sigs.append({"name": sig_name(s_.signal if hasattr(s_, "signal") else s_), "count": s_.count if hasattr(s_, "count") else s_.get("count")})
        entry["signals"] = sigs
    manifest.append(entry)

with open("repair_300_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f)
print(f"Wrote repair_300_manifest.json with {len(manifest)} entries")


def lua_sig(pair):
    if pair is None:
        return "nil"
    return '{name="%s",type="%s"}' % (pair["name"], pair["type"])


def lua_str(s):
    return '"%s"' % s


per_entity = []
for e in manifest:
    parts = [f'local e=surf.create_entity{{name={lua_str(e["name"])},position={{{e["x"]},{e["y"]}}},force=force,raise_built=false}}; ', "created=created+1; "]
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
        parts.append(f'e.get_or_create_control_behavior().parameters={{{",".join(aparts)}}}; ')
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
        parts.append(f'e.get_or_create_control_behavior().parameters={{conditions={{{",".join(conds)}}},outputs={{{",".join(outs)}}}}}; ')
    elif e["name"] == "constant-combinator":
        sig_entries = []
        for i, s_ in enumerate(e["signals"]):
            if s_["name"] is None:
                continue
            sig_entries.append(f'{{index={i+1},signal={{name="{s_["name"]}",type="virtual"}},count={s_["count"]}}}')
        parts.append(f'e.get_or_create_control_behavior().parameters={{{",".join(sig_entries)}}}; ')
    per_entity.append("".join(parts))

BATCH_SIZE = 20
n_batches = math.ceil(len(per_entity) / BATCH_SIZE)
for b in range(n_batches):
    chunk = per_entity[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
    batch_command = (
        "/c local surf=game.player.surface; local force=game.player.force; local created=0; "
        + "".join(chunk)
        + f'game.print("repair batch {b+1}/{n_batches}: created "..created.." entities")'
    )
    with open(f"repair_300_batch_{b+1}.txt", "w", encoding="utf-8") as f:
        f.write(batch_command)

print(f"Wrote {n_batches} batch files (repair_300_batch_1.txt .. repair_300_batch_{n_batches}.txt), {BATCH_SIZE} entities each")
