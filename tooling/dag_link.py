"""Build one transport link between two live blocks (see dag_lib.py).

NOTE: game.get_entity_by_unit_number does NOT work in this game/API (returns
nil) - every lookup is by (name, position) via ent_at() in LUA_LIB.
"""
import json
import math

from dag_lib import LUA_LIB, BUS_SIGS, Router, block, locate, lua, polyline_points, prep_area, wpos


class PlacementFailed(Exception):
    def __init__(self, point, made, subs):
        super().__init__(f"relay placement failed near {point} after {len(made)} relays")
        self.point, self.made, self.subs = point, made, subs


def destroy_positions(made, subs):
    for lst, nm in ((made, "arithmetic-combinator"), (subs, "substation")):
        for i in range(0, len(lst), 300):
            arr = ",".join(f"{{{x},{y}}}" for x, y in lst[i:i + 300])
            s = _safe(f'''
local ps = {{{arr}}}
for _, p in ipairs(ps) do
  local e = ent_at(p[1], p[2], "{nm}")
  if e then e.destroy() end
end
rcon.print("ok")
''')
            lua(s)


def _safe(body):
    return LUA_LIB + "local ok_, err_ = pcall(function()\n" + body + "\nend)\nif not ok_ then rcon.print('ERR ' .. tostring(err_)) end\n"


def _spine_pts(cells, side):
    ys = sorted({round(c[1], 1) for c in cells})
    xs = [c[0] for c in cells]
    x = (max(xs) + 7) if side > 0 else (min(xs) - 7)
    return [(x, y) for y in ys]


def _run(s, what, timeout=300):
    r = lua(s, timeout=timeout).strip()
    if not r or r.startswith("ERR"):
        raise RuntimeError(f"{what}: {r!r}")
    return r


def chain_lua(points, prev_pos, prev_sub, sub_every=2):
    arr = ",".join(f"{{{x:.2f},{y:.2f}}}" for x, y in points)
    pp = prev_pos or (0, 0)
    ps = prev_sub or (0, 0)
    s = _safe(f'''
local pts = {{{arr}}}
local prev = nil
if {1 if prev_pos else 0} > 0 then prev = ent_at({pp[0]}, {pp[1]}, "arithmetic-combinator") end
local prevsub = nil
if {1 if prev_sub else 0} > 0 then prevsub = ent_at({ps[0]}, {ps[1]}, "substation") end
if prev == nil and {1 if prev_pos else 0} > 0 then error("prev relay lost") end
local made, subs, failed, sfail = {{}}, {{}}, 0, 0
local lastdir = {{1,0}}
for j, p in ipairs(pts) do
  local e
  if prev then
    e = make_near("arithmetic-combinator", p[1], p[2], 2, prev.position.x, prev.position.y, 8.7)
  else
    e = make_near("arithmetic-combinator", p[1], p[2], 2, nil, nil, nil)
  end
  if not e then
    failed = j
    break
  end
  set_relay(e)
  if prev then
    local dxx, dyy = e.position.x - prev.position.x, e.position.y - prev.position.y
    local n = math.sqrt(dxx*dxx + dyy*dyy)
    if n > 0.01 then lastdir = {{dxx/n, dyy/n}} end
    link(prev, ROUT, e, RIN)
  end
  made[#made+1] = {{e.position.x, e.position.y}}
  if (j % {sub_every}) == 1 then
    local sx, sy = e.position.x - lastdir[2]*4, e.position.y + lastdir[1]*4
    local sb = make_near("substation", sx, sy, 3, nil, nil, nil)
    if sb then
      if prevsub then
        if not link(prevsub, POLE, sb, POLE) then sfail = sfail + 1 end
      end
      prevsub = sb
      subs[#subs+1] = {{sb.position.x, sb.position.y}}
    else
      sfail = sfail + 1
    end
  end
  prev = e
end
rcon.print(helpers.table_to_json({{made=made, subs=subs, failed=failed, sfail=sfail, last=(prev and {{prev.position.x, prev.position.y}} or {{0,0}}), lastsub=(prevsub and {{prevsub.position.x, prevsub.position.y}} or {{0,0}})}}))
''')
    return json.loads(_run(s, "chain_lua"))


def trace_chain(first_pos, limit=6000):
    s = _safe(f'''
local e = ent_at({first_pos[0]}, {first_pos[1]}, "arithmetic-combinator")
local made = {{}}
local seen = {{}}
for i=1,{limit} do
  made[#made+1] = {{e.position.x, e.position.y}}
  seen[e.unit_number] = true
  local nxt = nil
  for _, cn in pairs(e.get_wire_connector(ROUT, true).connections) do
    local t = cn.target.owner
    if t.valid and t.name == "arithmetic-combinator" and not seen[t.unit_number] then
      local p = t.get_control_behavior().parameters
      if p.first_signal and p.first_signal.name == "signal-each" and p.output_signal and p.output_signal.name == "signal-each" then nxt = t break end
    end
  end
  if not nxt then break end
  e = nxt
end
rcon.print(helpers.table_to_json(made))
''')
    return json.loads(_run(s, "trace_chain", 120))


def convert_lua(kind, cell_pos, insig, outsig, relays_near, cell_type):
    rl = ",".join(f"{{{x:.2f},{y:.2f}}}" for x, y in relays_near)
    dx = 3.5 if kind == "src" else -3.5
    cconn = "ROUT" if cell_type == "arithmetic-combinator" else "CRED"
    dst_conn = "CRED" if cell_type == "constant-combinator" else "RIN"
    s = _safe(f'''
local cell = ent_at({cell_pos[0]}, {cell_pos[1]}, "{cell_type}")
if not cell then error("cell not found") end
local rl = {{{rl}}}
if #rl == 0 then error("no relay near") end
local anchor = ent_at(rl[1][1], rl[1][2], "arithmetic-combinator")
if not anchor then error("anchor lost") end
local cx, cy = {cell_pos[0]} + ({dx}), {cell_pos[1]}
local e = make_near("arithmetic-combinator", cx, cy, 3, anchor.position.x, anchor.position.y, 8.7)
if not e then rcon.print("NOSPOT") return end
set_conv(e, "{insig}", "{outsig}")
local ok1, ok2
if "{kind}" == "src" then
  ok1 = link(cell, {cconn}, e, RIN)
  ok2 = link(e, ROUT, anchor, RIN)
else
  ok1 = link(anchor, ROUT, e, RIN)
  ok2 = link(e, ROUT, cell, {dst_conn})
end
rcon.print(tostring(ok1) .. "," .. tostring(ok2) .. "," .. e.position.x .. "," .. e.position.y)
''')
    return lua(s).strip()


def clear_constants(positions):
    arr = ",".join(f"{{{x},{y}}}" for x, y in positions)
    s = _safe(f'''
local ps = {{{arr}}}
local n = 0
for _, p in ipairs(ps) do
  local e = ent_at(p[1], p[2], "constant-combinator")
  if e then
    local sec = e.get_or_create_control_behavior().get_section(1)
    for i=1,20 do
      pcall(function() sec.clear_slot(i) end)
    end
    n = n + 1
  end
end
rcon.print(n)
''')
    return lua(s).strip()


def _build_link_once(spec, rt, verbose=True, resume_first=None):
    """spec: dict(name, src=[(block,id,in_sig)], dst=[(block,id,out_sig)], src_side=+1, dst_side=-1)"""
    name = spec["name"]
    src, dst = spec["src"], spec["dst"]
    assert len(src) == len(dst) <= len(BUS_SIGS)
    src_pos = []
    for b, i, insig in src:
        x, y = wpos(b, i)
        r = locate("arithmetic-combinator", x, y)
        if not r:
            raise RuntimeError(f"source cell not found {b}:{i} near {x},{y}")
        src_pos.append(r)
    dst_pos = []
    for b, i, outsig in dst:
        x, y = wpos(b, i)
        r = locate("constant-combinator", x, y)
        if not r:
            raise RuntimeError(f"dest const not found {b}:{i} near {x},{y}")
        dst_pos.append(r)
    ssp = _spine_pts(src_pos, spec.get("src_side", 1))
    dsp = _spine_pts(dst_pos, spec.get("dst_side", -1))
    bs, bd = block(src[0][0])["bbox"], block(dst[0][0])["bbox"]
    stub_s = (max(bs[2] + 60, ssp[-1][0] + 40), ssp[-1][1])
    stub_d = (min(bd[0] - 60, dsp[0][0] - 40), dsp[0][1])
    mid = rt.route(stub_s, stub_d)
    wps = list(ssp) + mid + list(dsp)
    pts = polyline_points(wps, 6.5)
    if verbose:
        print(f"[{name}] src cells {len(src)}, waypoints {len(wps)}, relay pts {len(pts)}, length ~{len(pts) * 6.5:.0f}")
    made, subs = [], []
    prev_p, prev_s = None, None
    if resume_first:
        made = trace_chain(resume_first)
        pts = []
    else:
        prep_area(pts)
    for i in range(0, len(pts), 150):
        seg = pts[i:i + 150]
        r = chain_lua(seg, prev_p, prev_s)
        made += r["made"]
        subs += r["subs"]
        if r["failed"]:
            raise PlacementFailed(seg[r["failed"] - 1], made, subs)
        if r["sfail"] and verbose:
            print(f"  substation link failures in chunk: {r['sfail']}")
        prev_p, prev_s = tuple(r["last"]), (tuple(r["lastsub"]) if r["lastsub"] != [0, 0] else None)
    if verbose:
        print(f"[{name}] chain: {len(made)} relays, {len(subs)} substations, first {made[0]}")

    def near_relays(px, py, n=3, rad=12.0):
        c = sorted(made, key=lambda m: (m[0] - px) ** 2 + (m[1] - py) ** 2)
        return [m for m in c[:n] if math.hypot(m[0] - px, m[1] - py) <= rad]

    res = []
    for k, ((b, i, insig), (x, y, u)) in enumerate(zip(src, src_pos)):
        res.append(convert_lua("src", (x, y), insig, BUS_SIGS[k], near_relays(x + 7, y), "arithmetic-combinator"))
    clear_constants([(x, y) for x, y, _ in dst_pos])
    for k, ((b, i, outsig), (x, y, u)) in enumerate(zip(dst, dst_pos)):
        res.append(convert_lua("dst", (x, y), BUS_SIGS[k], outsig, near_relays(x - 7, y), "constant-combinator"))
    if verbose:
        print(f"[{name}] converters: {res}")
    return dict(made=made, subs=subs, conv=res)


def cleanup_outside_blocks(x0, y0, x1, y1, pad=2.0):
    """Destroy relays/substations/converters in a region that lie OUTSIDE every block bbox."""
    from dag_lib import BLOCKS
    rects = []
    for n in BLOCKS:
        bx0, by0, bx1, by1 = block(n)["bbox"]
        rects.append(f"{{{bx0 - pad},{by0 - pad},{bx1 + pad},{by1 + pad}}}")
    s = _safe(f'''
local R = {{{",".join(rects)}}}
local function inside(x, y)
  for _, r in ipairs(R) do
    if x >= r[1] and x <= r[3] and y >= r[2] and y <= r[4] then return true end
  end
  return false
end
local n = 0
for _, e in pairs(S.find_entities_filtered{{area={{{{{x0},{y0}}},{{{x1},{y1}}}}}, name={{"arithmetic-combinator","substation"}}}}) do
  if not inside(e.position.x, e.position.y) then e.destroy() n = n + 1 end
end
rcon.print(n)
''')
    return _run(s, "cleanup", 300)


import os as _os
_BAD_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "dag_bad_cells.json")


def build_link(spec, verbose=True, retries=6):
    rt = Router()
    if _os.path.exists(_BAD_FILE):
        rt.extra_bad = {tuple(c) for c in json.load(open(_BAD_FILE))}
    for attempt in range(retries):
        try:
            return _build_link_once(spec, rt, verbose)
        except PlacementFailed as e:
            print(f"  attempt {attempt}: {e}; rerouting")
            destroy_positions(e.made, e.subs)
            c = rt.cell(e.point)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    rt.extra_bad.add((c[0] + dx, c[1] + dy))
            json.dump(sorted(rt.extra_bad), open(_BAD_FILE, "w"))
    raise RuntimeError("link failed after retries")
