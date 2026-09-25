"""Shared blueprint builder for the dense (Factorio 2.0 vector combinator) blocks.

Tracks occupied tiles (asserts no overlap) and entity centres (asserts every circuit wire is
short enough), so geometry bugs are caught at generation time, before circuit_sim and the game.
Serialization is done here, linearly: each entity's JSON comes from draftsman's per-entity to_dict()
(exact draftsman format, ~0.2 ms/entity), but entities are never added to a draftsman Blueprint -
its blueprint-level bookkeeping is what made generation quadratic (Reshenie 17).
"""
import base64
import json
import math
import zlib

from draftsman.entity import (ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface,
                              ElectricPole)

import sigkeys as SK

R, G = "red", "green"
SECTION_MAX = 1000      # filters per constant-combinator section (game limit: final_prims_test)
EACH, EVERYTHING = "signal-each", "signal-everything"
MAX_WIRE = 8.0          # centre-to-centre bound (real circuit reach 9)
BIG_REACH = 28.0        # big electric pole to big electric pole (real reach 30)


SUB_REACH = 17.0        # substation wire reach 18 (normal quality), centre-to-centre bound
SUB_SUPPLY = 9.0        # substation supply area half-size (normal quality)
BP_VERSION = 562949958467584
COMBINATORS = {"arithmetic-combinator", "decider-combinator", "selector-combinator"}


class Builder:
    def __init__(self, label):
        self.label = label
        self.ents = []              # (id, entity json without entity_number), in creation order
        self.wires = []             # (id_a, connector_a, id_b, connector_b)
        self.occ = {}
        self.pos = {}
        self.names = {}
        self.power_edges = []
        self.n_route_poles = 0

    def _add(self, eid, entity):
        d = entity.to_dict()
        self.ents.append((eid, d))
        self.names[eid] = d["name"]
        return eid

    def _conn(self, eid, side, color):
        red = color == R
        if self.names[eid] in COMBINATORS and side == "output":
            return 3 if red else 4
        return 1 if red else 2

    def power(self, a, b):
        self.wires.append((a, 5, b, 5))
        self.power_edges.append((a, b))

    def connect_power(self):
        """Kruskal over all substations (existing edges first); raises if the grid stays split."""
        subs = [e for e, n in self.names.items() if n == "substation"]
        parent = {s: s for s in subs}

        def find(s):
            while parent[s] != s:
                parent[s] = parent[parent[s]]
                s = parent[s]
            return s

        for a, b in self.power_edges:
            if a in parent and b in parent:
                parent[find(a)] = find(b)
        pairs = []
        cells = {}
        for s in subs:
            x, y = self.pos[s]
            cells.setdefault((int(x // SUB_REACH), int(y // SUB_REACH)), []).append(s)
        for s in subs:
            x, y = self.pos[s]
            cx, cy = int(x // SUB_REACH), int(y // SUB_REACH)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for t in cells.get((cx + dx, cy + dy), []):
                        if t > s:
                            d = math.dist(self.pos[s], self.pos[t])
                            if d <= SUB_REACH:
                                pairs.append((d, s, t))
        added = 0
        for d, s, t in sorted(pairs):
            if find(s) != find(t):
                parent[find(s)] = find(t)
                self.power(s, t)
                added += 1
        # bridge the remaining parts: closest substation pair between parts, chain of new substations
        for k in range(200):
            groups = {}
            for s in subs:
                groups.setdefault(find(s), []).append(s)
            if len(groups) <= 1:
                return added
            parts = list(groups.values())
            main = parts[0]
            others = [s for p in parts[1:] for s in p]
            d, a, t = min((math.dist(self.pos[a], self.pos[t]), a, t) for a in main for t in others)
            cur = a
            for j in range(100):
                if math.dist(self.pos[cur], self.pos[t]) <= SUB_REACH:
                    self.power(cur, t)
                    parent[find(cur)] = find(t)
                    added += 1
                    break
                spot = self._best_spot(self.pos[cur], SUB_REACH, self.pos[t], 2,
                                       math.dist(self.pos[cur], self.pos[t]) - 1.0)
                assert spot is not None, f"power bridge stuck at {cur}"
                sid = self.substation(f"pbridge_{k}_{j}", *spot)
                subs.append(sid)
                parent[sid] = sid
                self.power(cur, sid)
                parent[find(sid)] = find(cur)
                cur = sid
                added += 1
        raise AssertionError("power grid could not be joined")

    def unpowered(self):
        """Powered entities (not constants/poles) outside every substation's supply area."""
        subs = [self.pos[e] for e, n in self.names.items() if n == "substation"]
        out = []
        for e, n in self.names.items():
            if n in ("constant-combinator", "substation", "medium-electric-pole", "big-electric-pole",
                     "electric-energy-interface", "display-panel"):
                continue
            x, y = self.pos[e]
            if not any(abs(x - sx) <= SUB_SUPPLY and abs(y - sy) <= SUB_SUPPLY for sx, sy in subs):
                out.append(e)
        return out

    def _best_spot(self, centre, reach, target, size, beat):
        """Free size x size spot within `reach` of centre whose centre is closest to target (< beat)."""
        cx, cy = centre
        best, best_d = None, beat
        r = int(reach) + 1
        for tx in range(int(cx) - r - size, int(cx) + r + 1):
            for ty in range(int(cy) - r - size, int(cy) + r + 1):
                p = (tx + size / 2, ty + size / 2)
                if math.dist(p, centre) > reach:
                    continue
                d = math.dist(p, target)
                if d >= best_d:
                    continue
                if any((tx + dx, ty + dy) in self.occ for dx in range(size) for dy in range(size)):
                    continue
                best, best_d = (tx, ty), d
        return best

    def link(self, color, a, a_side, b_, b_side, tag):
        """Connect a (side) to b_ (side) on `color`: direct wire if short, else a greedy chain of poles
        through free space (zero latency, verified live): big poles (reach 30) jump over dense blocks,
        medium poles (reach 9) are the fallback near the ends. Returns the number of poles."""
        cur, cur_side, cur_big = a, a_side, False
        target = self.pos[b_]
        for k in range(2000):
            d = math.dist(self.pos[cur], target)
            if d <= MAX_WIRE:
                self.wire(color, cur, b_, s1=cur_side, s2=b_side)
                return k
            reach = BIG_REACH if cur_big else MAX_WIRE
            pid = f"{tag}_rp{k}"
            spot = self._best_spot(self.pos[cur], reach, target, 2, d - 1.0)
            if spot is not None:
                self.pole(pid, *spot, name="big-electric-pole", size=2)
            else:
                spot = self._best_spot(self.pos[cur], MAX_WIRE, target, 1, d - 1.0)
                assert spot is not None, f"route {tag}: stuck at {cur} {self.pos[cur]} -> {b_} {target}"
                self.pole(pid, *spot)
            self._wire_any(color, cur, pid, s1=cur_side)
            cur, cur_side, cur_big = pid, None, spot is not None and self.names[pid] == "big-electric-pole"
            self.n_route_poles += 1
        raise AssertionError(f"route {tag}: too long")

    def _wire_any(self, color, a, b, s1=None, s2=None):
        """Wire with the reach of the weaker end (big pole to big pole: BIG_REACH)."""
        big = self.names[a] == "big-electric-pole" and self.names[b] == "big-electric-pole"
        d = math.dist(self.pos[a], self.pos[b])
        assert d <= (BIG_REACH if big else MAX_WIRE), f"wire {a}->{b} too long: {d:.1f}"
        self.wires.append((a, self._conn(a, s1, color), b, self._conn(b, s2, color)))

    def _place(self, eid, x, y, w, h):
        assert eid not in self.pos, f"duplicate entity id {eid}"
        for dx in range(w):
            for dy in range(h):
                t = (x + dx, y + dy)
                assert t not in self.occ, f"{eid} overlaps {self.occ[t]} at {t}"
                self.occ[t] = eid
        self.pos[eid] = (x + w / 2, y + h / 2)

    def comb(self, cls, eid, x, y, **kw):
        self._place(eid, x, y, 1, 2)
        return self._add(eid, cls(id=eid, tile_position=(x, y), **kw))

    def entity(self, cls, eid, x, y, w, h, **kw):
        self._place(eid, x, y, w, h)
        return self._add(eid, cls(id=eid, tile_position=(x, y), **kw))

    def const(self, eid, x, y, sigs, section_max=SECTION_MAX, on=True):
        """sigs: {signal key (sigkeys): value}; spills into several sections of <= section_max filters.
        on=False: switched off (a button the player turns on in its GUI).
        JSON written directly (draftsman's per-signal validation costs ~0.2 ms per signal, i.e. minutes for
        the final model's ~400K weight signals); const_draftsman() is the reference it must equal."""
        self._place(eid, x, y, 1, 1)
        d = {"name": "constant-combinator", "position": {"x": x + 0.5, "y": y + 0.5}}
        if not on:
            d["control_behavior"] = {"is_on": False}
        items = [(k, v) for k, v in sigs.items()]
        if items:
            secs = []
            for s0 in range(0, len(items), section_max):
                filters = []
                for k, (key, v) in enumerate(items[s0:s0 + section_max]):
                    n, t, q = SK.split(key)
                    f = {"comparator": "=", "index": k + 1, "name": n, "count": v}
                    if t != "item":
                        f["type"] = t
                    f["quality"] = q
                    filters.append(f)
                secs.append({"index": len(secs) + 1, "filters": filters})
            d.setdefault("control_behavior", {})["sections"] = {"sections": secs}
        self.ents.append((eid, d))
        self.names[eid] = d["name"]
        return eid

    def const_draftsman(self, eid, x, y, sigs, section_max=SECTION_MAX):
        """The draftsman way (slow) - reference for const()."""
        self._place(eid, x, y, 1, 1)
        c = ConstantCombinator(id=eid, tile_position=(x, y))
        items = list(sigs.items())
        if len(items) <= section_max and all("|" not in k for k, _ in items):
            for k, (name, v) in enumerate(items):
                c.set_signal(index=k, name=name, count=v)
        else:
            for s0 in range(0, len(items), section_max):
                sec = c.add_section()
                for k, (key, v) in enumerate(items[s0:s0 + section_max]):
                    n, t, q = SK.split(key)
                    sec.set_signal(k, n, v, quality=q, type=t)
        return self._add(eid, c)

    def pole(self, eid, x, y, name="medium-electric-pole", size=1, **kw):
        self._place(eid, x, y, size, size)
        return self._add(eid, ElectricPole(name=name, id=eid, tile_position=(x, y), **kw))

    def substation(self, eid, x, y):
        return self.pole(eid, x, y, name="substation", size=2, quality="legendary")

    def eei(self, x, y, eid="power_source"):
        self._place(eid, x, y, 2, 2)
        return self._add(eid, ElectricEnergyInterface(name="electric-energy-interface", id=eid,
                                                      tile_position=(x, y), buffer_size=10 ** 9))

    def wire(self, color, a, b, s1=None, s2=None):
        (ax, ay), (bx, by) = self.pos[a], self.pos[b]
        d = math.hypot(ax - bx, ay - by)
        assert d <= MAX_WIRE, f"wire {a}->{b} too long: {d:.1f}"
        self.wires.append((a, self._conn(a, s1, color), b, self._conn(b, s2, color)))

    def arith(self, eid, x, y, first, op, second, out, w1=None, w2=None):
        """first/second: signal name or int constant; w1/w2: restrict that operand to one wire colour."""
        kw = dict(first_operand=SK.sid(first) if isinstance(first, str) else first, operation=op,
                  second_operand=SK.sid(second) if isinstance(second, str) else second, output_signal=SK.sid(out))
        if w1:
            kw["first_operand_wires"] = {w1}
        if w2:
            kw["second_operand_wires"] = {w2}
        return self.comb(ArithmeticCombinator, eid, x, y, **kw)

    def to_json(self):
        num = {}
        ents = []
        for k, (eid, d) in enumerate(self.ents, start=1):
            num[eid] = k
            ents.append({"entity_number": k, **d})
        wires = [[num[a], ca, num[b], cb] for a, ca, b, cb in self.wires]
        return {"blueprint": {"item": "blueprint", "label": self.label, "version": BP_VERSION,
                              "entities": ents, "wires": wires}}

    def result(self):
        raw = json.dumps(self.to_json(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        bp_string = "0" + base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
        idmap = [{"id": eid, "x": round(d["position"]["x"], 3), "y": round(d["position"]["y"], 3), "name": d["name"]}
                 for eid, d in self.ents]
        return bp_string, idmap


class Sub:
    """View of a Builder for one component: ids get a prefix, coordinates an offset."""

    def __init__(self, b, pfx, ox, oy):
        self.b, self.pfx, self.ox, self.oy = b, pfx, ox, oy
        sub = self

        class _Pos:
            def __getitem__(self, k):
                return sub.b.pos[sub.pfx + k]
        self.pos = _Pos()

    def id(self, e):
        return self.pfx + e

    def comb(self, cls, eid, x, y, **kw):
        return self.b.comb(cls, self.pfx + eid, self.ox + x, self.oy + y, **kw)

    def const(self, eid, x, y, sigs, **kw):
        return self.b.const(self.pfx + eid, self.ox + x, self.oy + y, sigs, **kw)

    def entity(self, cls, eid, x, y, w, h, **kw):
        return self.b.entity(cls, self.pfx + eid, self.ox + x, self.oy + y, w, h, **kw)

    def pole(self, eid, x, y, **kw):
        return self.b.pole(self.pfx + eid, self.ox + x, self.oy + y, **kw)

    def substation(self, eid, x, y):
        return self.b.substation(self.pfx + eid, self.ox + x, self.oy + y)

    def arith(self, eid, x, y, *a, **kw):
        return self.b.arith(self.pfx + eid, self.ox + x, self.oy + y, *a, **kw)

    def wire(self, color, a, b_, s1=None, s2=None):
        self.b.wire(color, self.pfx + a, self.pfx + b_, s1=s1, s2=s2)

    def power(self, a, b_):
        self.b.power(self.pfx + a, self.pfx + b_)


def cond(sig, cmp, c, net=None, ct="or"):
    kw = dict(first_signal=SK.sid(sig), comparator=cmp, constant=c, compare_type=ct)
    if net:
        kw["first_signal_networks"] = {net}
    return DeciderCombinator.Condition(**kw)


def out_const(sig, value):
    return DeciderCombinator.Output(signal=SK.sid(sig), copy_count_from_input=False, constant=value)


def out_copy(sig, net=None):
    kw = dict(signal=SK.sid(sig), copy_count_from_input=True)
    if net:
        kw["networks"] = {net}
    return DeciderCombinator.Output(**kw)
