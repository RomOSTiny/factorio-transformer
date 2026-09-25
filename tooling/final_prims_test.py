"""Live micro-test of the primitives the final (d=256) model relies on, before any generator work:

  wide_*    constant with N mixed-type signals (virtual/item/fluid/entity/recipe/...) -> dot product
            each(red A) * each(green B) -> S in ONE combinator, and a pass each+0 -> each to count what
            arrives (N = 256, 1000, 1200 in 2 sections, all 2169 in 3 sections)
  qual      the same name in 5 qualities = 5 distinct signals?
  emb_N     decider "P = 3 -> N constant outputs" (embedding row), N = 256 and 600
  exp       decider "each <= 150 -> each = 7" over 300 mixed-type keys
  sel       selector max over 300 mixed-type keys
  wdiv      each(green) * 10000 / S(red) -> each over mixed-type keys

  python final_prims_test.py sim            offline expectations (circuit_sim)
  python final_prims_test.py build|check|clear X Y
"""
import json
import sys

from draftsman.entity import DeciderCombinator, SelectorCombinator

import sigkeys as SK
from circuit_builder import EACH, G, R, Builder, cond, out_const

POOL = SK.pool(2169, exclude={"signal-S", "signal-P"})       # every usable normal-quality signal
# a constant with > 1000 filters in ONE section is not built by the game at all (checked live: 1200)
WIDE = [("w256", 256, 1000), ("w1000", 1000, 1000), ("w1200s", 1200, 600), ("wall", len(POOL), 1000)]


def av(i):
    return (i % 97) - 48 or 49


def bv(i):
    return (i % 13) - 6 or 7


def build():
    b = Builder("final prims test")
    y = 0
    exp = {}
    for tag, n, smax in WIDE:
        keys = POOL[:n]
        b.const(f"{tag}_a", 0, y, {k: av(i) for i, k in enumerate(keys)}, section_max=smax)
        b.const(f"{tag}_b", 1, y, {k: bv(i) for i, k in enumerate(keys)}, section_max=smax)
        b.arith(f"{tag}_dot", 2, y, EACH, "*", EACH, "signal-S", R, G)
        b.arith(f"{tag}_pass", 3, y, EACH, "+", 0, EACH, R)
        b.const(f"{tag}_sd", 4, y, {})
        b.const(f"{tag}_sp", 5, y, {})
        b.wire(R, f"{tag}_a", f"{tag}_dot", s2="input")
        b.wire(G, f"{tag}_b", f"{tag}_dot", s2="input")
        b.wire(R, f"{tag}_dot", f"{tag}_pass", s1="input", s2="input")
        b.wire(R, f"{tag}_dot", f"{tag}_sd", s1="output")
        b.wire(R, f"{tag}_pass", f"{tag}_sp", s1="output")
        exp[f"{tag}_dot"] = {"signal-S": sum(av(i) * bv(i) for i in range(n))}
        exp[f"{tag}_pass"] = {"count": n, "sum": sum(av(i) for i in range(n))}
        y += 2
    # qualities
    qk = [SK.key(n, t, q) for n, t in (("signal-A", "virtual"), ("iron-plate", "item")) for q in SK.QUALITIES]
    b.const("qual_a", 0, y, {k: 10 + i for i, k in enumerate(qk)})
    b.arith("qual_pass", 1, y, EACH, "+", 0, EACH, R)
    b.const("qual_sp", 2, y, {})
    b.wire(R, "qual_a", "qual_pass", s2="input")
    b.wire(R, "qual_pass", "qual_sp", s1="output")
    exp["qual_pass"] = {k: 10 + i for i, k in enumerate(qk)}
    y += 2
    # embedding-row deciders
    b.const("p_src", 0, y, {"signal-P": 3})
    prev = "p_src"
    for n in (256, 600):
        keys = POOL[:n]
        b.comb(DeciderCombinator, f"emb{n}", 1 + (n > 256) * 2, y, conditions=[cond("signal-P", "=", 3)],
               outputs=[out_const(k, 1 + i) for i, k in enumerate(keys)])
        b.const(f"emb{n}_sp", 2 + (n > 256) * 2, y, {})
        b.wire(R, prev, f"emb{n}", s1=None if prev == "p_src" else "input", s2="input")
        b.wire(R, f"emb{n}", f"emb{n}_sp", s1="output")
        prev = f"emb{n}"
        exp[f"emb{n}"] = {"count": n, "sum": n * (n + 1) // 2}
    y += 2
    # exp step decider, selector, wdiv on 300 mixed keys
    keys = POOL[1000:1300]
    b.const("k_src", 0, y, {k: 1 + i for i, k in enumerate(keys)})
    b.comb(DeciderCombinator, "exp", 1, y, conditions=[cond(EACH, "<=", 150)], outputs=[out_const(EACH, 7)])
    b.comb(SelectorCombinator, "sel", 2, y, operation="select", select_max=True, index_constant=0)
    b.arith("e4", 3, y, EACH, "*", 10000, EACH)
    b.const("s_src", 4, y, {"signal-S": 3000})
    b.arith("wdiv", 5, y, EACH, "/", "signal-S", EACH, G, R)
    b.const("exp_sp", 6, y, {})
    b.const("sel_sp", 7, y, {})
    b.const("wdiv_sp", 8, y, {})
    b.wire(R, "k_src", "exp", s2="input")
    b.wire(R, "exp", "sel", s1="input", s2="input")
    b.wire(R, "sel", "e4", s1="input", s2="input")
    b.wire(G, "e4", "wdiv", s1="output", s2="input")
    b.wire(R, "s_src", "wdiv", s2="input")
    b.wire(R, "exp", "exp_sp", s1="output")
    b.wire(R, "sel", "sel_sp", s1="output")
    b.wire(R, "wdiv", "wdiv_sp", s1="output")
    exp["exp"] = {"count": 150, "sum": 7 * 150}
    exp["sel"] = {keys[-1]: 300}
    exp["wdiv"] = {"count": 300, "sum": sum((1 + i) * 10000 // 3000 for i in range(300))}
    y += 2
    b.substation("sub", 10, 0)
    b.substation("sub2", 10, y - 2)
    b.power("sub", "sub2")
    b.eei(12, 0)
    return b, exp


def summarize(sig):
    return {"count": len(sig), "sum": sum(sig.values())}


def check(got, exp):
    ok = True
    for name, e in exp.items():
        g = got.get(name, {})
        cmp = summarize(g) if "count" in e else g
        good = cmp == e
        ok &= good
        print(f"{'OK ' if good else 'BAD'} {name:12s} expect {e}  got {cmp}")
    return ok


SINKS = {**{f"{t}_dot": f"{t}_sd" for t, _, _ in WIDE}, **{f"{t}_pass": f"{t}_sp" for t, _, _ in WIDE},
         "qual_pass": "qual_sp", "emb256": "emb256_sp", "emb600": "emb600_sp", "exp": "exp_sp", "sel": "sel_sp",
         "wdiv": "wdiv_sp"}


def sim(b, exp):
    from circuit_sim import Sim
    bp, idmap = b.result()
    s = Sim(bp)
    s.settle()
    num = {e["id"]: k + 1 for k, e in enumerate(idmap)}
    got = {name: s.net(num[sink], 1) for name, sink in SINKS.items()}
    return check(got, exp)


def live_read(blk):
    """Every sink's red network, keyed like sigkeys (type/quality aware)."""
    body = ", ".join(f'["{k}"] = SIG(F({blk.at(sink)}))' for k, sink in SINKS.items())
    r = blk.jlua('local s = game.surfaces["nauvis"]; '
                 'local function F(n, x, y) local r = s.find_entities_filtered{name=n, position={x, y}, radius=0.3}; '
                 'if #r == 1 then return r[1] end; return nil end; '
                 'local function SIG(e) local t = {}; if not e then return t end; for _, v in pairs(e.get_signals(defines.wire_connector_id.circuit_red) or {}) do '
                 't[v.signal.name .. "|" .. (v.signal.type or "item") .. "|" .. (v.signal.quality or "normal")] = v.count end; '
                 'return t end; '
                 f'rcon.print(helpers.table_to_json({{{body}}}))')
    out = {}
    for k in SINKS:
        v = r.get(k)
        out[k] = {SK.key(*kk.split("|")): c for kk, c in v.items()} if isinstance(v, dict) else {}
    return out


def filters_count(blk):
    """Filters per section as the game stored them, for the wide constants."""
    ids = [f"{t}_a" for t, _, _ in WIDE]
    body = ", ".join(f'["{i}"] = C(F({blk.at(i)}))' for i in ids)
    return blk.jlua('local s = game.surfaces["nauvis"]; '
                    'local function F(n, x, y) local r = s.find_entities_filtered{name=n, position={x, y}, radius=0.3}; '
                    'if #r == 1 then return r[1] end; return nil end; '
                    'local function C(e) local t = {}; if not e then return t end; local cb = e.get_control_behavior(); '
                    'for i = 1, cb.sections_count do table.insert(t, cb.get_section(i).filters_count) end; return t end; '
                    f'rcon.print(helpers.table_to_json({{{body}}}))')


if __name__ == "__main__":
    b, exp = build()
    mode = sys.argv[1]
    if mode == "sim":
        print("SIM", "OK" if sim(b, exp) else "MISMATCH")
        sys.exit()
    from block_live import LiveBlock
    bp, idmap = b.result()
    open("final_prims_bp.txt", "w").write(bp)
    json.dump(idmap, open("final_prims_ids.json", "w"))
    blk = LiveBlock("final_prims_bp.txt", "final_prims_ids.json", float(sys.argv[2]), float(sys.argv[3]), margin=10)
    if mode == "clear":
        print(blk.clear())
    elif mode == "build":
        print(blk.recon())
        print(blk.build()[:3])
        print({k: v for k, v in blk.verify().items() if k in ("entities", "missing_entities", "wires_missing", "status")})
    if mode in ("build", "check"):
        print("filters per section:", filters_count(blk))
        print("LIVE", "OK" if check(live_read(blk), exp) else "MISMATCH")
    blk.close()
