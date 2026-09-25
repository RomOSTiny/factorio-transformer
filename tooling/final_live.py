"""Live runner for the FINAL model (final_blueprint.txt / final_ids.json / final_info.json from sim_final_run.py
or final_gen.py).

  python final_live.py recon  X Y   generate chunks over the whole area, report water / entity types
  python final_live.py prep   X Y   destroy trees, rocks, cliffs, fish, enemies in the area
  python final_live.py build  X Y   upload the blueprint in parts (Lua storage), build_blueprint, revive
  python final_live.py verify X Y   READ-ONLY: every entity and circuit wire vs the blueprint + statuses
  python final_live.py ask    X Y "question" [--fresh]   type the question into the in-game console, press
                                    SEND, follow the reply on the board (--fresh: RESET first and compare
                                    with final_ref)
  python final_live.py status X Y   clock, position, reply line
  python final_live.py clear  X Y   destroy everything of force "player" in the area
"""
import json
import sys
import time

import numpy as np

MODE, TX, TY = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
EXTRA = sys.argv[4:]
sys.argv = sys.argv[:1]
from block_live import FIND, S, LiveBlock, esc
from final_blocks import CHARS, DELIVERY_CODE

sys.stdout.reconfigure(encoding="utf-8")
blk = LiveBlock("final_blueprint.txt", "final_ids.json", TX, TY, margin=20, timeout=900.0)
info = json.load(open("final_info.json"))
SIG = info["signals"]
VOCAB = info["vocab"]
CTX, Tp, Tc = info["ctx"], info["Tp"], info["Tc"]
NL = CHARS.index("\n")


def chunked_area_lua(body_fn, step=128):
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


def clock():
    return blk.read({"clk": (info["clock"], "combinator_output_red")})["clk"].get(SIG["clk"], 0)


def read_reply():
    """Reply cells (the board's reply line): token ids, -1 = empty."""
    got = blk.read({f"r{i}": (rid, "combinator_input_green") for i, rid in enumerate(info["reply"])})
    out = []
    for i in range(len(info["reply"])):
        c = {k: v for k, v in got[f"r{i}"].items() if v}
        out.append(VOCAB.index(next(iter(c))) if len(c) == 1 and next(iter(c)) in VOCAB else -1)
    while out and out[-1] == -1:
        out.pop()
    return out


def set_query(text):
    """Type the query into the console slots (what the player does by hand)."""
    m = {sid: ({VOCAB[CHARS.index(text[k])]: 1} if k < len(text) else {}) for k, sid in enumerate(info["slots"])}
    items = list(m.items())
    for i in range(0, len(items), 50):
        blk.set_consts(dict(items[i:i + 50]))


def press(eid):
    """Turn a button (constant combinator) on, then off - like the player in its GUI."""
    for on in ("true", "false"):
        blk.lua(S + FIND + f'F({blk.at(eid)}).get_control_behavior().enabled = {on}')
        time.sleep(0.3)


def normalize_query(text):
    sys.path.insert(0, DELIVERY_CODE)
    from tokenizer import normalize
    return normalize(text.replace("\n", " "))[:100]


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
    tot = 0
    for line in chunked_area_lua(lambda a: f'local n = 0; for _, e in pairs(s.find_entities_filtered{{area={a}, force="player"}}) do '
                                 'if e.type ~= "character" then e.destroy(); n = n + 1 end end; rcon.print(n)'):
        tot += int(line)
    print("destroyed", tot)
elif MODE == "build":
    bp = blk.bp_string
    blk.lua('storage.fbp = {}; rcon.print("reset")')
    step = 200_000
    t0 = time.time()
    for k, i in enumerate(range(0, len(bp), step)):
        blk.lua(f'storage.fbp[{k + 1}] = "{bp[i:i + step]}"; rcon.print(#storage.fbp)')
    print("uploaded", blk.lua('rcon.print(#table.concat(storage.fbp))').strip(), "of", len(bp), f"{time.time() - t0:.0f}s", flush=True)
    t0 = time.time()
    print(blk.lua(S + 'local inv = game.create_inventory(1); inv[1].set_stack{name="blueprint"}; '
                  'local ok = inv[1].import_stack(table.concat(storage.fbp)); '
                  f'local built = inv[1].build_blueprint{{surface=s, force=game.forces["player"], position={{x={TX}, y={TY}}}, force_build=true}}; '
                  'inv.destroy(); storage.fbp = nil; rcon.print("import=" .. tostring(ok) .. " built=" .. #built)').strip(),
          f"{time.time() - t0:.0f}s", flush=True)
    for p in range(2000):
        r = blk.jlua(S + f'local g = s.find_entities_filtered{{area={blk.area}, type="entity-ghost", limit=400}}; local n = 0; '
                     'for _, x in pairs(g) do if x.valid and x.revive{raise_revive=false} then n = n + 1 end end; '
                     f'rcon.print(helpers.table_to_json({{tried=#g, revived=n, left=s.count_entities_filtered{{area={blk.area}, type="entity-ghost"}}}}))')
        if p % 25 == 0 or r["left"] == 0 or r["revived"] == 0:
            print("revive", p, r, flush=True)
        if r["left"] == 0 or r["revived"] == 0:
            break
elif MODE == "verify":
    r = blk.verify(chunk=3000)
    r["miss_list"] = r["miss_list"][:10]
    r["bad_wires"] = r["bad_wires"][:5]
    print(json.dumps(r, indent=1))
elif MODE == "ask":
    # python final_live.py ask X Y "question" [--fresh]: type it into the console, press SEND, wait for the
    # reply on the board; with --fresh (RESET first) the reply is compared with final_ref's greedy decoding
    import final_ref as F
    q = normalize_query(EXTRA[0])
    fresh = "--fresh" in EXTRA
    if fresh:
        press(info["reset"])
    set_query(q)
    time.sleep(0.5)
    press(info["send"])
    t0 = time.time()
    print(f"you: {q}", flush=True)
    shown, last_change, prev_clk = 0, time.time(), -1
    for _ in range(100000):
        time.sleep(1.0)
        rep = read_reply()
        txt = "".join(CHARS[t] if t >= 0 else "?" for t in rep)
        if len(rep) > shown:
            print(f"  [{time.time() - t0:5.0f}s] bot: {txt!r}", flush=True)
            shown = len(rep)
        c = clock()
        if c != prev_clk:
            prev_clk, last_change = c, time.time()
        if (rep and rep[-1] == NL) or time.time() - last_change > 3 * Tp / 60 + 5:
            break
    reply = "".join(CHARS[t] for t in rep if t >= 0).rstrip("\n")
    print(f"bot: {reply}   [{time.time() - t0:.0f}s, position {clock() // Tp}]", flush=True)
    if fresh:
        M = F.IntModel()
        ids = [CHARS.index(c) for c in f"you: {q}\nbot: "]
        ref = "".join(CHARS[t] for t in M.generate(ids, max_new=150, stop_nl=True)).rstrip("\n")
        print(f"reference: {ref}")
        print("LIVE FINAL CHAT", "OK" if ref == reply else "DIFFERS")
elif MODE == "status":
    c = clock()
    rep = read_reply()
    print(f"clock {c} position {c // Tp} phase {c % Tp}; reply {''.join(CHARS[t] if t >= 0 else '?' for t in rep)!r}")

blk.close()
