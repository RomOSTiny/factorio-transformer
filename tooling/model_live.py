"""Live runner for the whole model (model_blueprint.txt from sim_run.py / model_gen.py).

  python model_live.py recon  X Y   generate chunks over the whole area, report water / entity types
  python model_live.py prep   X Y   destroy trees, rocks, cliffs, fish and enemy bases in the area
  python model_live.py build  X Y   upload the blueprint in chunks (Lua storage), build_blueprint, revive
  python model_live.py verify X Y   READ-ONLY: every entity and circuit wire vs the blueprint + statuses
  python model_live.py run    X Y   RST, RUN, follow the clock; compare each position's argmax with the
                                    reference (sim_run's expectations), print the token buffer at the end
  python model_live.py status X Y   clock, position, current letter, token buffer text
  python model_live.py clear  X Y   destroy everything of force "player" in the area
"""
import json
import sys
import time

import numpy as np

MODE, TX, TY = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
sys.argv = sys.argv[:1]
from block_live import FIND, S, LiveBlock, esc

blk = LiveBlock("model_blueprint.txt", "model_ids.json", TX, TY, margin=20, timeout=600.0)
info = json.load(open("model_info.json"))
SIG = info["signals"]


def chunked_area_lua(body_fn, step=128):
    """Run body_fn(area_lua) over the block area in square tiles (keeps each command short)."""
    out = []
    x0, x1, y0, y1 = TX - blk.hx, TX + blk.hx, TY - blk.hy, TY + blk.hy
    y = y0
    while y < y1:
        x = x0
        while x < x1:
            out.append(blk.lua(S + body_fn(f"{{{{{x},{y}}},{{{min(x + step, x1)},{min(y + step, y1)}}}}}")))
            x += step
        y += step
    return out


if MODE == "recon":
    r = int(max(blk.hx, blk.hy) // 32) + 2
    print(blk.lua(S + f's.request_to_generate_chunks({{{TX},{TY}}}, {r}); s.force_generate_chunk_requests(); rcon.print("chunks ok")'))
    tot, water = {}, 0
    for line in chunked_area_lua(lambda a: f'local cnt = {{}}; for _, e in pairs(s.find_entities_filtered{{area={a}}}) do '
                                 'cnt[e.type] = (cnt[e.type] or 0) + 1 end; '
                                 f'rcon.print(helpers.table_to_json({{w = s.count_tiles_filtered{{area={a}, collision_mask="water_tile"}}, c = cnt}}))'):
        d = json.loads(line)
        water += d["w"]
        for k, v in (d["c"] if isinstance(d["c"], dict) else {}).items():
            tot[k] = tot.get(k, 0) + v
    print(f"area {2 * blk.hx:.0f} x {2 * blk.hy:.0f}, water tiles {water}, entities {tot}")
elif MODE == "prep":
    n = 0
    for line in chunked_area_lua(lambda a: f'local n = 0; for _, e in pairs(s.find_entities_filtered{{area={a}, '
                                 'type={"tree", "simple-entity", "cliff", "fish", "unit-spawner", "turret", "unit", "corpse"}}) do '
                                 'if e.valid then e.destroy(); n = n + 1 end end; rcon.print(n)'):
        n += int(line)
    print("destroyed", n)
elif MODE == "clear":
    print(blk.clear())
elif MODE == "build":
    bp = blk.bp_string
    blk.lua('storage.model_bp = ""; rcon.print("reset")')
    step = 200_000
    for i in range(0, len(bp), step):
        blk.lua(f'storage.model_bp = storage.model_bp .. "{bp[i:i + step]}"; rcon.print(#storage.model_bp)')
    print("uploaded", blk.lua('rcon.print(#storage.model_bp)').strip(), "of", len(bp))
    t0 = time.time()
    print(blk.lua(S + 'local inv = game.create_inventory(1); inv[1].set_stack{name="blueprint"}; '
                  'local ok = inv[1].import_stack(storage.model_bp); '
                  f'local built = inv[1].build_blueprint{{surface=s, force=game.forces["player"], position={{x={TX}, y={TY}}}, force_build=true}}; '
                  'inv.destroy(); storage.model_bp = nil; rcon.print("import=" .. tostring(ok) .. " built=" .. #built)').strip(),
          f"{time.time() - t0:.0f}s")
    for p in range(1000):
        r = blk.jlua(S + f'local g = s.find_entities_filtered{{area={blk.area}, type="entity-ghost", limit=400}}; local n = 0; '
                     'for _, x in pairs(g) do if x.valid and x.revive{raise_revive=false} then n = n + 1 end end; '
                     f'rcon.print(helpers.table_to_json({{tried=#g, revived=n, left=s.count_entities_filtered{{area={blk.area}, type="entity-ghost"}}}}))')
        if p % 20 == 0 or r["left"] == 0 or r["revived"] == 0:
            print("revive", p, r, flush=True)
        if r["left"] == 0 or r["revived"] == 0:
            break
elif MODE == "verify":
    r = blk.verify(chunk=3000)
    r["miss_list"] = r["miss_list"][:10]
    r["bad_wires"] = r["bad_wires"][:5]
    print(json.dumps(r, indent=1))
elif MODE in ("run", "status"):
    import stage2_real_ref as R
    from stage2_tokenizer import decode, encode
    vocab = info["vocab"]
    ctx, Tp, Tc = info["ctx"], info["Tp"], info["Tc"]
    ptoks = encode(info["prompt"])
    toks = list(ptoks)
    while len(toks) < ctx:
        toks.append(int(np.argmax(R.forward(toks)[len(toks) - 1])))
    expect_next = [int(np.argmax(v)) for v in R.forward(toks)]
    cell = lambda j: (f"ctl_cell_{j}", "circuit_green") if j < len(ptoks) else (f"ctl_hold_{j}", "combinator_input_green")

    def state():
        reads = {"clk": ("ctl_clk_acc", "combinator_output_red"), "next": ("next_sink", "circuit_red")}
        return blk.read(reads)

    def buffer():
        got = blk.read({f"c{j}": cell(j) for j in range(ctx)})
        out = []
        for j in range(ctx):
            c = got[f"c{j}"]
            out.append(vocab.index(next(iter(c))) if len(c) == 1 else -1)
        return out

    if MODE == "run":
        blk.set_consts({info["cmd"]: {SIG["rst"]: 1}})
        time.sleep(0.5)
        blk.set_consts({info["cmd"]: {SIG["run"]: 1}})
        t0 = time.time()
        print(f"prompt {info['prompt']!r}; expected continuation {decode(toks[len(ptoks):])!r}")
        bad, seen = 0, set()
        for _ in range(100000):
            st = state()
            clk = st["clk"].get(SIG["clk"], 0)
            i, ph = divmod(clk, Tp)
            if ph >= Tc + 20 and i not in seen and i < ctx - 1:
                seen.add(i)
                nxt = st["next"].get(SIG["next"], 0)
                ok = nxt == expect_next[i]
                bad += not ok
                print(f"pos {i:2d} clock {clk} next {nxt:2d} ({decode([nxt])!r}) ref {expect_next[i]:2d} {'OK' if ok else 'BAD'}"
                      f"  {time.time() - t0:.0f}s", flush=True)
            if len(seen) == ctx - 1:
                break
            time.sleep(0.5)
        time.sleep(Tp / 60 + 1)
        buf = buffer()
        print(f"token buffer: {decode([t for t in buf if t >= 0])!r}")
        print("buffer == reference:", buf == toks, f"mismatches {bad}")
        print("LIVE MODEL", "OK" if bad == 0 and buf == toks else "FAILED")
    else:
        st = state()
        clk = st["clk"].get(SIG["clk"], 0)
        buf = buffer()
        print(f"clock {clk} position {clk // Tp} phase {clk % Tp}; buffer {decode([t for t in buf if t >= 0])!r}")
blk.close()
