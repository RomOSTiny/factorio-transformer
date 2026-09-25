"""Live runner for the dense KV-cache attention test (stage2_attn_kv_test.py).

Usage (cwd = tooling, Factorio via Host Saved Game):
  python attn_kv_live.py recon  X Y   area survey (entities by type, water tiles)
  python attn_kv_live.py build  X Y   build_blueprint + batched revive
  python attn_kv_live.py verify X Y   READ-ONLY: every blueprint entity and circuit wire present? power?
  python attn_kv_live.py run    X Y   drive all positions (q/k/v/W via the *_src constants), compare att
  python attn_kv_live.py clear  X Y   destroy everything of force "player" in the block area
Positions are resolved from the blueprint (entity centres + offset measured on the EEI).
"""
import base64
import json
import sys
import time
import zlib

import rcon_client

MODE, TX, TY = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
BP_FILE, IDS_FILE, EXP_FILE = "attn_kv_test_blueprint.txt", "attn_kv_test_ids.json", "attn_kv_test_expect.json"
bp_string = open(BP_FILE).read().strip()
BP = json.loads(zlib.decompress(base64.b64decode(bp_string[1:])))["blueprint"]
ids = json.load(open(IDS_FILE))
xs = [e["x"] for e in ids]; ys = [e["y"] for e in ids]
HX, HY = (max(xs) - min(xs)) / 2 + 30, (max(ys) - min(ys)) / 2 + 30
AREA = f"{{{{{TX - HX},{TY - HY}}},{{{TX + HX},{TY + HY}}}}}"
S = 'local s = game.surfaces["nauvis"]; '
c = rcon_client.connect(timeout=120.0)


def lua(body):
    out = c.command("/c local ok, err = pcall(function() " + body + " end) if not ok then rcon.print('LUA_ERROR ' .. tostring(err)) end")
    if "LUA_ERROR" in out:
        raise RuntimeError(out)
    return out


def jlua(body):
    return json.loads(lua(body))


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


if MODE == "recon":
    print(lua(S + f's.request_to_generate_chunks({{{TX},{TY}}}, 4); s.force_generate_chunk_requests(); '
              f'local cnt = {{}}; for _, e in pairs(s.find_entities_filtered{{area={AREA}}}) do cnt[e.type] = (cnt[e.type] or 0) + 1 end; '
              f'local w = s.count_tiles_filtered{{area={AREA}, collision_mask="water_tile"}}; '
              'rcon.print("water=" .. w .. " " .. helpers.table_to_json(cnt))'))
    sys.exit()

if MODE == "clear":
    print(lua(S + f'local n = 0; for _, e in pairs(s.find_entities_filtered{{area={AREA}, force="player"}}) do '
              'if e.type ~= "character" then e.destroy(); n = n + 1 end end; rcon.print("destroyed=" .. n)'))
    sys.exit()

if MODE == "build":
    print(lua(S + f's.request_to_generate_chunks({{{TX},{TY}}}, 4); s.force_generate_chunk_requests(); '
              'local inv = game.create_inventory(1); inv[1].set_stack{name="blueprint"}; '
              f'inv[1].import_stack("{bp_string}"); '
              f'local built = inv[1].build_blueprint{{surface=s, force=game.forces["player"], position={{x={TX}, y={TY}}}, force_build=true}}; '
              'inv.destroy(); rcon.print("built=" .. #built)'))
    for p in range(20):
        r = jlua(S + f'local g = s.find_entities_filtered{{area={AREA}, type="entity-ghost", limit=400}}; local n = 0; '
                 'for _, x in pairs(g) do if x.valid and x.revive{raise_revive=false} then n = n + 1 end end; '
                 f'rcon.print(helpers.table_to_json({{tried=#g, revived=n, left=s.count_entities_filtered{{area={AREA}, type="entity-ghost"}}}}))')
        print("revive batch", p, r)
        if r["left"] == 0 or r["revived"] == 0:
            break
    sys.exit()

# ---- offset from the unique EEI ----
eei_local = next(e for e in ids if e["id"] == "power_source")
live = jlua(S + f'local e = s.find_entities_filtered{{area={AREA}, name="electric-energy-interface"}}; '
            'rcon.print(helpers.table_to_json({n=#e, x=e[1] and e[1].position.x, y=e[1] and e[1].position.y}))')
assert live["n"] == 1, live
OX, OY = live["x"] - eei_local["x"], live["y"] - eei_local["y"]
print(f"offset local->world ({OX}, {OY})")
num2 = {e["entity_number"]: e for e in BP["entities"]}
W_ = lambda e: (e["name"], round(e["position"]["x"] + OX, 3), round(e["position"]["y"] + OY, 3))
FIND = ('local function F(n, x, y) local r = s.find_entities_filtered{name=n, position={x, y}, radius=0.3}; '
        'if #r == 1 then return r[1] end; return nil end; ')

if MODE == "verify":
    ents = [list(W_(e)) for e in BP["entities"]]
    wires = [[*W_(num2[a]), ca, *W_(num2[b]), cb] for a, ca, b, cb in BP["wires"] if ca <= 4 and cb <= 4]
    body = (S + FIND + f'local E = helpers.json_to_table("{esc(json.dumps(ents))}"); '
            f'local WW = helpers.json_to_table("{esc(json.dumps(wires))}"); '
            'local miss_e, miss_w, ok_w, dup = {}, 0, 0, 0; '
            'for i = 1, #E do local r = s.find_entities_filtered{name=E[i][1], position={E[i][2], E[i][3]}, radius=0.3}; '
            '  if #r == 0 then table.insert(miss_e, E[i][1] .. "@" .. E[i][2] .. "," .. E[i][3]) elseif #r > 1 then dup = dup + 1 end end; '
            'local bad_w = {}; '
            'for i = 1, #WW do local w = WW[i]; local a, b = F(w[1], w[2], w[3]), F(w[5], w[6], w[7]); local found = false; '
            '  if a and b then for _, cn in pairs(a.get_wire_connector(w[4], true).connections) do '
            '    if cn.target.owner.unit_number == b.unit_number and cn.target.wire_connector_id == w[8] then found = true end end end; '
            '  if found then ok_w = ok_w + 1 else miss_w = miss_w + 1; if #bad_w < 10 then table.insert(bad_w, w) end end end; '
            'local st = {}; for _, e in pairs(s.find_entities_filtered{area=' + AREA + '}) do '
            '  if e.type:find("combinator") then local k = e.name .. ":" .. tostring(e.status); st[k] = (st[k] or 0) + 1 end end; '
            'rcon.print(helpers.table_to_json({entities=#E, missing_entities=#miss_e, miss_list={table.unpack(miss_e, 1, 10)}, '
            'duplicates=dup, wires=#WW, wires_ok=ok_w, wires_missing=miss_w, bad_wires=bad_w, status=st}))')
    r = jlua(body)
    print(json.dumps(r, indent=1))
    print("status codes: 1=working, see defines.entity_status")
    sys.exit()

# ---- run ----
X = json.load(open(EXP_FILE))
dims = X["dims"]
pos = {e["id"]: (e["name"], e["x"] + OX, e["y"] + OY) for e in ids}


def at(eid):
    n, x, y = pos[eid]
    return f'"{n}", {x}, {y}'


def setter(eid, sigs):
    items = [[k, v] for k, v in sigs.items() if v]
    return (f'do local cb = F({at(eid)}).get_or_create_control_behavior(); '
            'if cb.sections_count < 1 then cb.add_section() end; local sec = cb.get_section(1); '
            'for i = 1, 40 do sec.clear_slot(i) end; '
            f'local L = helpers.json_to_table("{esc(json.dumps(items))}"); '
            'for i = 1, #L do sec.set_slot(i, {value={type="virtual", name=L[i][1], quality="normal"}, min=L[i][2]}) end end; ')


def vec(v):
    return {dims[d]: int(x) for d, x in enumerate(v) if x}


READ = (S + FIND + 'local function SIG(e, cid) local t = {}; for _, v in pairs(e.get_signals(cid) or {}) do t[v.signal.name] = v.count end; return t end; '
        f'rcon.print(helpers.table_to_json({{att = SIG(F({at("att_sink")}), defines.wire_connector_id.circuit_red), tick = game.tick}}))')
lua(S + FIND + setter("ctl_src", {"signal-R": 1}))          # clear the cache first
time.sleep(0.3)
lua(S + FIND + setter("ctl_src", {}))
bad = 0
t0 = time.time()
for i, st in enumerate(X["steps"]):
    lua(S + FIND + setter("q_src", vec(st["q"])) + setter("k_src", vec(st["k"])) + setter("v_src", vec(st["v"]))
        + setter("ctl_src", {"signal-W": i + 1}))
    time.sleep(0.2)
    lua(S + FIND + setter("ctl_src", {}))
    time.sleep(0.3)
    got = jlua(READ)["att"]
    exp = vec(st["att"])
    ok = got == exp
    bad += not ok
    diff = {k: (got.get(k), exp.get(k)) for k in set(got) | set(exp) if got.get(k) != exp.get(k)}
    print(f"pos {i:2d} {'OK ' if ok else 'BAD'} n={len(got)}" + ("" if ok else f" diff(live,ref)={dict(list(diff.items())[:6])}"))
print(f"positions {len(X['steps'])}, mismatches {bad}, {time.time() - t0:.0f}s")
print("LIVE ATTENTION", "OK" if bad == 0 else "FAILED")
