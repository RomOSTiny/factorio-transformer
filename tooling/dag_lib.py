"""Live DAG linker for the Sequencer smoke model.

Connects the 13 already-built blocks with wired transport lines instead of
build-time constants: latch cells -> converters (in_sig -> bus signal) ->
relay chain (signal-each * 1) -> converters (bus signal -> input signal)
feeding the downstream input cells. Route is planned in Python (A* around
block bboxes), entities are created via RCON Lua (no `--` comments in Lua).
"""
import heapq
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rcon_client import connect  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
BUS_SIGS = [f"signal-{c}" for c in LETTERS] + [f"signal-{d}" for d in "0123456789"]

BLOCKS = {
    "embed": ("stage2_embed_param_ids.json", (6600, 5000)),
    "ln_attn": ("stage2_layernorm2_param_ids.json", (5000, 3600)),
    "ln_ffn": ("stage2_layernorm2_param_ids.json", (4000, 3600)),
    "ln_final": ("stage2_layernorm3_param_ids.json", (4000, 4750)),
    "qkv": ("stage2_matmul_param_ids.json", (6600, 4200)),
    "proj": ("stage2_matmul_proj_param_ids.json", (7000, 4200)),
    "fc1": ("stage2_matmul_fc1_param_ids.json", (7800, 4200)),
    "fc2": ("stage2_matmul_fc2_param_ids.json", (8600, 4200)),
    "logits": ("stage2_matmul_logits_param_ids.json", (9200, 4200)),
    "res1": ("stage2_residual1_param_ids.json", (10000, 4200)),
    "res2": ("stage2_residual2_param_ids.json", (10800, 4200)),
    "argmax": ("stage2_argmax_param_ids.json", (11000, 4200)),
    "attn": ("stage2_attention_param_ids.json", (6600, 6800)),
}

_cache = {}


def block(name):
    if name in _cache:
        return _cache[name]
    fn, target = BLOCKS[name]
    m = json.load(open(os.path.join(HERE, fn)))
    xs = [e["x"] for e in m]
    ys = [e["y"] for e in m]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    off = (target[0] - cx, target[1] - cy)
    ids = {e["id"]: (e["x"] + off[0], e["y"] + off[1], e["name"]) for e in m}
    bbox = (min(xs) + off[0], min(ys) + off[1], max(xs) + off[0], max(ys) + off[1])
    _cache[name] = dict(ids=ids, off=off, bbox=bbox)
    return _cache[name]


def wpos(name, eid):
    x, y, _ = block(name)["ids"][eid]
    return x, y


def lua(script, timeout=120):
    assert "--" not in script, "no -- comments in RCON Lua"
    with connect(timeout=timeout) as c:
        return c.command("/c " + " ".join(script.split("\n")))


LUA_LIB = r'''
local S = game.surfaces["nauvis"]
local F = game.forces["player"]
local RIN = defines.wire_connector_id.combinator_input_red
local ROUT = defines.wire_connector_id.combinator_output_red
local CRED = defines.wire_connector_id.circuit_red
local POLE = defines.wire_connector_id.pole_copper
local OFFS = {}
for dx=-3,3 do for dy=-3,3 do OFFS[#OFFS+1] = {dx, dy, dx*dx+dy*dy} end end
table.sort(OFFS, function(a,b) return a[3] < b[3] end)
local function clear_deco(x, y, r)
  for _, e in pairs(S.find_entities_filtered{area={{x-r,y-r},{x+r,y+r}}, type={"tree","simple-entity","cliff","fish"}}) do
    if e.valid then e.destroy() end
  end
end
local function can(name, px, py)
  return S.can_place_entity{name=name, position={px,py}, force=F, direction=defines.direction.north}
end
local function make_near(name, x, y, r, px0, py0, maxd)
  local big = (name == "substation")
  for _, o in ipairs(OFFS) do
    if o[3] <= r*r + r*r then
      local px, py
      if big then px, py = math.floor(x) + o[1], math.floor(y) + o[2]
      else px, py = math.floor(x) + 0.5 + o[1], math.floor(y + 0.5) + o[2] end
      local ok = true
      if px0 and maxd then
        if (px-px0)*(px-px0) + (py-py0)*(py-py0) > maxd*maxd then ok = false end
      end
      if ok then
        if not can(name, px, py) then
          clear_deco(px, py, 2.0)
        end
        if can(name, px, py) then
          local e = S.create_entity{name=name, position={px,py}, force=F, direction=defines.direction.north, raise_built=false, quality=(big and "legendary" or nil)}
          if e then return e end
        end
      end
    end
  end
  return nil
end
local function set_relay(e)
  e.get_or_create_control_behavior().parameters = {first_signal={type="virtual",name="signal-each"}, operation="*", second_constant=1, output_signal={type="virtual",name="signal-each"}}
end
local function set_conv(e, insig, outsig)
  e.get_or_create_control_behavior().parameters = {first_signal={type="virtual",name=insig}, operation="+", second_constant=0, output_signal={type="virtual",name=outsig}}
end
local function link(a, ca, b, cb)
  return a.get_wire_connector(ca, true).connect_to(b.get_wire_connector(cb, true), false, defines.wire_origin.script)
end
local function ent_at(x, y, name)
  local f = S.find_entities_filtered{area={{x-0.3,y-0.3},{x+0.3,y+0.3}}, name=name, limit=1}
  return f[1]
end
local function dist(a, b)
  return math.sqrt((a.position.x-b.position.x)^2 + (a.position.y-b.position.y)^2)
end
'''


def prep_area(points, step=48, radius=40):
    """Generate chunks and clear enemy nests near points."""
    pts = points[:: max(1, int(step // 6.5))] + [points[-1]]
    chunks = []
    for i in range(0, len(pts), 60):
        seg = pts[i:i + 60]
        arr = ",".join(f"{{{x},{y}}}" for x, y in seg)
        s = LUA_LIB + f'''
local pts = {{{arr}}}
for _, p in ipairs(pts) do S.request_to_generate_chunks({{p[1],p[2]}}, 2) end
S.force_generate_chunk_requests()
local killed = 0
for _, p in ipairs(pts) do
  for _, e in pairs(S.find_entities_filtered{{position={{p[1],p[2]}}, radius={radius}, type={{"unit-spawner","turret"}}, force="enemy"}}) do
    e.destroy() killed = killed + 1
  end
end
rcon.print(killed)
'''
        chunks.append(lua(s, timeout=300).strip())
    return chunks


def polyline_points(wps, hop=6.5):
    pts = [wps[0]]
    for a, b in zip(wps, wps[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, math.ceil(d / hop))
        for k in range(1, n + 1):
            t = k / n
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return pts


class Router:
    CELL = 20
    X0, Y0, X1, Y1 = 3200, 2200, 11600, 8100

    def __init__(self, margin=30):
        self.blocked = set()
        self.extra_bad = set()
        for n in BLOCKS:
            x0, y0, x1, y1 = block(n)["bbox"]
            for cx in range(int((x0 - margin - self.X0) // self.CELL), int((x1 + margin - self.X0) // self.CELL) + 1):
                for cy in range(int((y0 - margin - self.Y0) // self.CELL), int((y1 + margin - self.Y0) // self.CELL) + 1):
                    self.blocked.add((cx, cy))

    def cell(self, p):
        return (int((p[0] - self.X0) // self.CELL), int((p[1] - self.Y0) // self.CELL))

    def center(self, c):
        return (self.X0 + c[0] * self.CELL + self.CELL / 2, self.Y0 + c[1] * self.CELL + self.CELL / 2)

    def route(self, a, b):
        sc, gc = self.cell(a), self.cell(b)
        openq = [(0, sc)]
        g = {sc: 0}
        prev = {}
        W = int((self.X1 - self.X0) // self.CELL)
        H = int((self.Y1 - self.Y0) // self.CELL)
        while openq:
            _, c = heapq.heappop(openq)
            if c == gc:
                break
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    n = (c[0] + dx, c[1] + dy)
                    if not (0 <= n[0] < W and 0 <= n[1] < H):
                        continue
                    if n != gc and n != sc and (n in self.blocked or n in self.extra_bad):
                        continue
                    if dx != 0 and dy != 0:
                        if ((c[0] + dx, c[1]) in self.blocked) or ((c[0], c[1] + dy) in self.blocked):
                            continue
                    ng = g[c] + math.hypot(dx, dy)
                    if ng < g.get(n, 1e18):
                        g[n] = ng
                        prev[n] = c
                        h = math.hypot(gc[0] - n[0], gc[1] - n[1])
                        heapq.heappush(openq, (ng + h, n))
        if gc not in prev and gc != sc:
            raise RuntimeError("no route")
        cells = [gc]
        while cells[-1] != sc:
            cells.append(prev[cells[-1]])
        cells.reverse()
        pts = [self.center(c) for c in cells]
        pts = self.simplify(pts)
        return [a] + pts[1:-1] + [b]

    def los(self, p, q):
        n = int(math.hypot(q[0] - p[0], q[1] - p[1]) / (self.CELL / 2)) + 1
        for k in range(n + 1):
            t = k / n
            c = self.cell((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
            if c in self.blocked or c in self.extra_bad:
                return False
        return True

    def simplify(self, pts):
        out = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1 and not self.los(pts[i], pts[j]):
                j -= 1
            out.append(pts[j])
            i = j
        return out


def locate(name_type, x, y, tol=1.6):
    s = LUA_LIB + f'''
local f = S.find_entities_filtered{{area={{{{{x-tol},{y-tol}}},{{{x+tol},{y+tol}}}}}, name="{name_type}"}}
local best, bd = nil, 1e9
for _, e in pairs(f) do
  local d = (e.position.x-{x})^2 + (e.position.y-{y})^2
  if d < bd then bd = d best = e end
end
if best then rcon.print(best.position.x .. "," .. best.position.y .. "," .. best.unit_number) else rcon.print("NF") end
'''
    r = lua(s).strip()
    if r == "NF":
        return None
    px, py, un = r.split(",")
    return float(px), float(py), int(un)
