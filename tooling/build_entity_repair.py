import io
import contextlib
import json

PURE_OFFSET = (-61.0, -135.0)

g = {"__name__": "__not_main__"}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(compile(open("export_full.py").read(), "export_full.py", "exec"), g)

bp = g["bp"]
dump = json.load(open(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\factorio_ai_debug.json", encoding="utf-8"))

TYPE_OFFSET = {
    "constant-combinator": (0.5, 0.5),
    "arithmetic-combinator": (0.5, 1.0),
    "decider-combinator": (0.5, 1.0),
}


def tile_xy(e):
    p = e.tile_position
    return (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])


def real_pos(e):
    tx, ty = tile_xy(e)
    tox, toy = TYPE_OFFSET[e.name]
    return (round(tx + tox + PURE_OFFSET[0], 1), round(ty + toy + PURE_OFFSET[1], 1))


expected = {}
for e in bp.entities:
    if e.name not in TYPE_OFFSET:
        continue
    expected[real_pos(e) + (e.name,)] = e

actual = set()
for r in dump:
    actual.add((round(r["x"], 1), round(r["y"], 1), r["type"]))

missing_keys = set(expected.keys()) - actual
print(f"Missing: {len(missing_keys)}")


COMPARATOR_MAP = {"≥": ">=", "≤": "<=", "≠": "!=", "=": "=", ">": ">", "<": "<"}


def norm_cmp(c):
    return COMPARATOR_MAP.get(c, c)


def sig_pair(sig):
    """-> {"name":..., "type":...} or None, for embedding as a Factorio SignalID"""
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
for key in missing_keys:
    rx, ry, name = key
    e = expected[key]
    entry = {"name": name, "x": rx, "y": ry}
    if name == "arithmetic-combinator":
        entry["op"] = e.operation
        entry["out"] = sig_pair(e.output_signal)
        fo = e.first_operand
        so = e.second_operand
        if isinstance(fo, (int, float)):
            entry["fo_const"] = fo
        else:
            entry["fo_sig"] = sig_pair(fo)
        if isinstance(so, (int, float)):
            entry["so_const"] = so
        else:
            entry["so_sig"] = sig_pair(so)
    elif name == "decider-combinator":
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
    elif name == "constant-combinator":
        sigs = []
        cb = e.sections if hasattr(e, "sections") else None
        # draftsman ConstantCombinator stores signals differently across
        # versions - try the common attribute
        try:
            for s in e.signals:
                sigs.append({"name": sig_name(s.signal if hasattr(s, "signal") else s), "count": s.count if hasattr(s, "count") else s.get("count")})
        except Exception as ex:
            entry["_signals_error"] = str(ex)
        entry["signals"] = sigs
    manifest.append(entry)

with open("entity_repair_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f)

print(f"Wrote entity_repair_manifest.json with {len(manifest)} entries")
print("Sample entry:", json.dumps(manifest[0], indent=2) if manifest else None)
