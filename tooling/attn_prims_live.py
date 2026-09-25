"""Live runner for stage2_attn_prims_test.py (build, revive, read, KV-cell write/hold/reset sequence).

Usage (cwd = tooling, Factorio via Host Saved Game):
  python attn_prims_live.py recon X Y     area survey only
  python attn_prims_live.py clear X Y     destroy everything of force "player" in the test area
  python attn_prims_live.py build X Y     build + revive
  python attn_prims_live.py check X Y     read all sub-tests + run the KV-cell sequence
"""
import json
import sys
import time

import rcon_client

MODE, TX, TY = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
spec = json.load(open("attn_prims_ids.json"))
ids = {e["id"]: e for e in spec["ids"]}
xs = [e["x"] for e in spec["ids"]]; ys = [e["y"] for e in spec["ids"]]
CX, CY = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
HX, HY = (max(xs) - min(xs)) / 2 + 20, (max(ys) - min(ys)) / 2 + 20
AREA = f"{{{{{TX - HX},{TY - HY}}},{{{TX + HX},{TY + HY}}}}}"

c = rcon_client.connect(timeout=60.0)


def lua(body):
    out = c.command("/c local ok, err = pcall(function() " + body + " end) if not ok then rcon.print('LUA_ERROR ' .. tostring(err)) end")
    if "LUA_ERROR" in out:
        raise RuntimeError(out)
    return out


S = 'local s = game.surfaces["nauvis"]; '

if MODE == "recon":
    print(lua(S + f's.request_to_generate_chunks({{{TX},{TY}}}, 3); s.force_generate_chunk_requests(); '
              f'local es = s.find_entities_filtered{{area={AREA}}}; local cnt = {{}}; '
              'for _, e in pairs(es) do cnt[e.type] = (cnt[e.type] or 0) + 1 end; '
              f'local w = s.count_tiles_filtered{{area={AREA}, collision_mask="water_tile"}}; '
              'rcon.print("water=" .. w .. " " .. helpers.table_to_json(cnt))'))
    sys.exit()

if MODE == "clear":
    print(lua(S + f'local n = 0; for _, e in pairs(s.find_entities_filtered{{area={AREA}, force="player"}}) do '
              'if e.type ~= "character" then e.destroy(); n = n + 1 end end; rcon.print("destroyed=" .. n)'))
    sys.exit()

if MODE == "build":
    bp = open("attn_prims_blueprint.txt").read().strip()
    print(lua(S + f's.request_to_generate_chunks({{{TX},{TY}}}, 3); s.force_generate_chunk_requests(); '
              'local inv = game.create_inventory(1); inv[1].set_stack{name="blueprint"}; '
              f'inv[1].import_stack("{bp}"); '
              f'local built = inv[1].build_blueprint{{surface=s, force=game.forces["player"], position={{x={TX}, y={TY}}}, force_build=true}}; '
              'inv.destroy(); rcon.print("built=" .. #built)'))
    print(lua(S + f'local n, f = 0, 0; for _, g in pairs(s.find_entities_filtered{{area={AREA}, type="entity-ghost"}}) do '
              'local r = g.revive{raise_revive=false}; if r then n = n + 1 else f = f + 1 end end; '
              'rcon.print("revived=" .. n .. " failed=" .. f)'))
    sys.exit()

# ---- check ----
sel = ids["d_sel"]
off = json.loads(lua(S + f'local e = s.find_entities_filtered{{area={AREA}, name="selector-combinator"}}; '
                     'rcon.print(helpers.table_to_json({n=#e, x=e[1].position.x, y=e[1].position.y}))'))
assert off["n"] == 1, off
OX, OY = off["x"] - sel["x"], off["y"] - sel["y"]
print(f"offset local->world ({OX}, {OY})")

FIND = ('local function F(n, x, y) local r = s.find_entities_filtered{name=n, position={x, y}, radius=0.6}; '
        'if #r ~= 1 then error("find " .. n .. " at " .. x .. "," .. y .. " -> " .. #r) end; return r[1] end; '
        'local function SIG(e, cid) local t = {}; for _, v in pairs(e.get_signals(cid) or {}) do t[v.signal.name] = v.count end; return t end; ')


def at(eid):
    e = ids[eid]
    return f'"{e["name"]}", {e["x"] + OX}, {e["y"] + OY}'


# entity census in the area: statuses
print(lua(S + f'local cnt = {{}}; for _, e in pairs(s.find_entities_filtered{{area={AREA}}}) do '
          'if e.type:find("combinator") then local k = e.name .. ":" .. tostring(e.status); cnt[k] = (cnt[k] or 0) + 1 end end; '
          'rcon.print(helpers.table_to_json(cnt))'))

W = "defines.wire_connector_id"
reads = {
    "a": ("a_sink", f"{W}.circuit_red"), "b": ("b_sink", f"{W}.circuit_red"), "c": ("c_sink", f"{W}.circuit_red"),
    "d_sel": ("d_m", f"{W}.combinator_input_red"), "d": ("d_sink", f"{W}.circuit_red"),
    "e": ("e_sink", f"{W}.circuit_red"), "f": ("f_sink", f"{W}.circuit_red"), "h": ("h_sink", f"{W}.circuit_red"),
}
body = S + FIND + "local out = {}; "
for k, (eid, cid) in reads.items():
    body += f'out["{k}"] = SIG(F({at(eid)}), {cid}); '
body += f'out.params_a = F({at("a_ar")}).get_control_behavior().parameters; '
body += 'rcon.print(helpers.table_to_json(out))'
got = json.loads(lua(body))
ok_all = True
for k, exp in spec["expect"].items():
    ok = got[k] == exp
    ok_all &= ok
    print(f"{k:6s} {'OK ' if ok else 'BAD'} got={got[k]} expect={exp}")
print("live params a_ar:", json.dumps(got["params_a"]))

# ---- g: KV cells ----
CTL, H1, H2, DATA = at("g_ctl"), at("g_hold1"), at("g_hold2"), at("g_data")


def set_ctl(w, r):
    slots = ""
    for i, (name, v) in enumerate((("signal-W", w), ("signal-R", r)), start=1):
        slots += (f'sec.set_slot({i}, {{value={{type="virtual", name="{name}", quality="normal"}}, min={v}}}); ' if v
                  else f'sec.clear_slot({i}); ')
    lua(S + FIND + f'local cb = F({CTL}).get_or_create_control_behavior(); '
        'if cb.sections_count < 1 then cb.add_section() end; local sec = cb.get_section(1); ' + slots)


def set_data(a):
    lua(S + FIND + f'local sec = F({DATA}).get_control_behavior().get_section(1); '
        f'sec.set_slot(1, {{value={{type="virtual", name="signal-A", quality="normal"}}, min={a}}})')


def cells():
    time.sleep(0.5)
    r = json.loads(lua(S + FIND + f'rcon.print(helpers.table_to_json({{c1 = SIG(F({H1}), {W}.combinator_input_green), '
                               f'c2 = SIG(F({H2}), {W}.combinator_input_green), tick = game.tick}}))'))
    return r["c1"], r["c2"]


E = {}
AB = {"signal-A": 11, "signal-B": 22}
seq = [
    ("start (W=0)", lambda: set_ctl(0, 0), (E, E)),
    ("write cell1 (W=1)", lambda: set_ctl(1, 0), (AB, E)),
    ("release (W=0)", lambda: set_ctl(0, 0), (AB, E)),
    ("data A=99, no write", lambda: set_data(99), (AB, E)),
    ("write cell2 (W=2)", lambda: set_ctl(2, 0), (AB, {"signal-A": 99, "signal-B": 22})),
    ("release (W=0)", lambda: set_ctl(0, 0), (AB, {"signal-A": 99, "signal-B": 22})),
    ("reset (R=1)", lambda: set_ctl(0, 1), (E, E)),
    ("reset released (R=0)", lambda: set_ctl(0, 0), (E, E)),
    ("restore data A=11", lambda: set_data(11), (E, E)),
]
for name, act, (e1, e2) in seq:
    act()
    c1, c2 = cells()
    ok = c1 == e1 and c2 == e2
    ok_all &= ok
    print(f"g {name:24s} {'OK ' if ok else 'BAD'} cell1={c1} cell2={c2}")
print("ALL OK" if ok_all else "SOME FAILED")
c.close()
