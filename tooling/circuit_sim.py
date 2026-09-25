"""Tick-level simulator of a Factorio 2.0 blueprint's circuit network (offline gate before live builds).

Semantics (the subset this project uses, checked against live micro-tests):
  - networks = connected components of wires per colour; poles are plain junctions;
    a network's value is the sum of the outputs of its constant/combinator members
  - combinators output at tick t+1 what they compute from their input networks at tick t;
    constants output immediately; zero-valued signals do not exist
  - arithmetic: operands are signals or constants with red/green network selection;
    `each` iterates over the signals of the networks selected for the each-operand(s)
    (both-each = red[s] op green[s]); output `each` = per signal, specific = sum
  - decider: conditions joined by and/or (and binds tighter); `each` in conditions
    iterates signals; outputs: specific / each / everything, copy (from the output's
    networks) or constant
  - selector: `select` mode, select_max, index_constant
Division truncates toward zero, x/0 = 0; int32 overflow wraps like the game and is recorded per
entity in Sim.ovf — non-empty after settle() means a real (settled) overflow.
"""
import base64
import json
import zlib
from collections import defaultdict

import sigkeys as SK

RED_IN, GREEN_IN, RED_OUT, GREEN_OUT = 1, 2, 3, 4
I32 = 2 ** 31


def decode(bp_string):
    return json.loads(zlib.decompress(base64.b64decode(bp_string.strip()[1:])))["blueprint"]


def _nets(sel):
    sel = sel or {}
    return (sel.get("red", True), sel.get("green", True))


def _sig(s):
    return SK.from_json(s)


def _tdiv(a, b):
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


OPS = {
    "*": lambda a, b: a * b, "+": lambda a, b: a + b, "-": lambda a, b: a - b, "/": _tdiv,
    "%": lambda a, b: 0 if b == 0 else a - _tdiv(a, b) * b,
    ">>": lambda a, b: a >> (b & 31), "<<": lambda a, b: a << (b & 31),
    "AND": lambda a, b: a & b, "OR": lambda a, b: a | b, "XOR": lambda a, b: a ^ b,
}
CMP = {"<": lambda a, b: a < b, ">": lambda a, b: a > b, "=": lambda a, b: a == b, "≤": lambda a, b: a <= b,
       "≥": lambda a, b: a >= b, "≠": lambda a, b: a != b, "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b,
       "!=": lambda a, b: a != b, "==": lambda a, b: a == b}


_OVF = [False]


def _chk(v):
    """int32 wrap-around like the game; flags the overflow (transients may overflow harmlessly,
    a settled output must not — see Sim.ovf)."""
    if not -I32 <= v < I32:
        _OVF[0] = True
        v = (v + I32) % (2 * I32) - I32
    return v


class Sim:
    def __init__(self, bp_string):
        bp = decode(bp_string)
        self.ents = {e["entity_number"]: e for e in bp["entities"]}
        self.by_pos = {(e["position"]["x"], e["position"]["y"]): n for n, e in self.ents.items()}
        parent = {}

        def node(en, cid):
            e = self.ents[en]
            if "combinator" not in e["name"] or e["name"] == "constant-combinator":
                cid = 1 if cid in (1, 3) else 2          # constants/poles: one connector per colour
            return (en, cid)

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for w in bp.get("wires", []):
            a, b = node(w[0], w[1]), node(w[2], w[3])
            if w[1] > 4 or w[3] > 4:
                continue                                  # copper
            parent[find(a)] = find(b)
        self.net_of = {}
        members = defaultdict(list)
        for n in list(parent):
            members[find(n)].append(n)
        for root, nodes in members.items():
            for nd in nodes:
                self.net_of[nd] = root
        self.sources = defaultdict(list)                  # net -> [(entity, is_red)]
        self.readers = defaultdict(set)                   # net -> {entity}
        self.combs = []
        self.consts = {}
        for n, e in self.ents.items():
            name = e["name"]
            if name == "constant-combinator":
                self.consts[n] = self._const_signals(e)
                for cid in (1, 2):
                    if (n, cid) in self.net_of:
                        self.sources[self.net_of[(n, cid)]].append(n)
            elif name in ("arithmetic-combinator", "decider-combinator", "selector-combinator"):
                self.combs.append(n)
                for cid in (RED_OUT, GREEN_OUT):
                    if (n, cid) in self.net_of:
                        self.sources[self.net_of[(n, cid)]].append(n)
                for cid in (RED_IN, GREEN_IN):
                    if (n, cid) in self.net_of:
                        self.readers[self.net_of[(n, cid)]].add(n)
        self.out = {n: {} for n in self.combs}
        self.ovf = {}
        self.netval = {}
        self.tick = 0
        for net in self.sources:
            self._recompute(net)
        self.dirty = set(self.combs)

    @staticmethod
    def _const_signals(e):
        cb = e.get("control_behavior", {})
        if cb.get("is_on", True) is False:
            return {}
        out = defaultdict(int)
        for sec in cb.get("sections", {}).get("sections", []):
            for f in sec.get("filters", []):
                out[SK.from_json(f)] += f.get("count", 0)
        return {k: v for k, v in out.items() if v}

    def _recompute(self, net):
        tot = defaultdict(int)
        for n in self.sources[net]:
            src = self.consts[n] if n in self.consts else self.out[n]
            for k, v in src.items():
                tot[k] += v
        self.netval[net] = {k: _chk(v) for k, v in tot.items() if v}

    def _inputs(self, n):
        r = self.netval.get(self.net_of.get((n, RED_IN)), {})
        g = self.netval.get(self.net_of.get((n, GREEN_IN)), {})
        return r, g

    @staticmethod
    def _get(sig, nets, r, g):
        return (r.get(sig, 0) if nets[0] else 0) + (g.get(sig, 0) if nets[1] else 0)

    @staticmethod
    def _keys(nets, r, g):
        return (set(r) if nets[0] else set()) | (set(g) if nets[1] else set())

    def _arith(self, e, r, g):
        p = e.get("control_behavior", {}).get("arithmetic_conditions", {})
        f, s, o = _sig(p.get("first_signal")), _sig(p.get("second_signal")), _sig(p.get("output_signal"))
        fn, sn = _nets(p.get("first_signal_networks")), _nets(p.get("second_signal_networks"))
        op = OPS[p.get("operation", "*")]
        fc, sc = p.get("first_constant", 0), p.get("second_constant", 0)
        out = defaultdict(int)
        each_keys = set()
        if f == "signal-each":
            each_keys |= self._keys(fn, r, g)
        if s == "signal-each":
            each_keys |= self._keys(sn, r, g)
        if each_keys or f == "signal-each" or s == "signal-each":
            for k in each_keys:
                a = self._get(k, fn, r, g) if f == "signal-each" else (self._get(f, fn, r, g) if f else fc)
                b = self._get(k, sn, r, g) if s == "signal-each" else (self._get(s, sn, r, g) if s else sc)
                v = op(a, b)
                out[k if o == "signal-each" else o] += v
        elif o:
            a = self._get(f, fn, r, g) if f else fc
            b = self._get(s, sn, r, g) if s else sc
            out[o] += op(a, b)
        return {k: _chk(v) for k, v in out.items() if v and k}

    def _decider(self, e, r, g):
        p = e.get("control_behavior", {}).get("decider_conditions", {})
        conds = p.get("conditions", [])
        outs = p.get("outputs", [])
        uses_each = any(_sig(c.get("first_signal")) == "signal-each" for c in conds)

        def ev(each_val):
            groups, cur = [], []
            for i, c in enumerate(conds):
                if i > 0 and c.get("compare_type", "or") == "or":
                    groups.append(cur)
                    cur = []
                fsig = _sig(c.get("first_signal"))
                assert fsig not in ("signal-everything", "signal-anything"), "not simulated"
                a = each_val if fsig == "signal-each" else self._get(fsig, _nets(c.get("first_signal_networks")), r, g)
                ssig = _sig(c.get("second_signal"))
                b = self._get(ssig, _nets(c.get("second_signal_networks")), r, g) if ssig else c.get("constant", 0)
                cur.append(CMP[c.get("comparator", "<")](a, b))
            groups.append(cur)
            return any(all(gr) for gr in groups if gr)

        out = defaultdict(int)
        if uses_each:
            nets = (True, True)
            for c in conds:
                if _sig(c.get("first_signal")) == "signal-each":
                    nets = _nets(c.get("first_signal_networks"))
            passing = [k for k in self._keys(nets, r, g) if ev(self._get(k, nets, r, g))]
        else:
            passing = None
            if not ev(None):
                return {}
        for o in outs:
            sig, copy, onets = _sig(o.get("signal")), o.get("copy_count_from_input", True), _nets(o.get("networks"))
            const = o.get("constant", 1)
            if sig == "signal-each":
                assert passing is not None, "decider each-output without each condition is dropped by the game"
                for k in passing:
                    out[k] += self._get(k, onets, r, g) if copy else const
            elif sig == "signal-everything":
                for k in self._keys(onets, r, g):
                    out[k] += self._get(k, onets, r, g) if copy else const
            elif sig:
                if passing is not None and not passing:
                    continue
                out[sig] += self._get(sig, onets, r, g) if copy else const
        return {k: _chk(v) for k, v in out.items() if v}

    def _selector(self, e, r, g):
        cb = e.get("control_behavior", {})
        assert cb.get("operation", "select") == "select"
        tot = defaultdict(int)
        for d in (r, g):
            for k, v in d.items():
                tot[k] += v
        items = sorted(((v, k) for k, v in tot.items() if v), reverse=cb.get("select_max", True))
        i = cb.get("index_constant", 0)
        return {items[i][1]: items[i][0]} if i < len(items) else {}

    def set_const(self, n, signals):
        self.consts[n] = {k: v for k, v in signals.items() if v}
        for cid in (1, 2):
            net = self.net_of.get((n, cid))
            if net is not None:
                self._recompute(net)
                self.dirty |= self.readers[net]

    def step(self, ticks=1):
        for _ in range(ticks):
            if not self.dirty:
                self.tick += ticks
                return
            new = {}
            for n in self.dirty:
                e = self.ents[n]
                r, g = self._inputs(n)
                nm = e["name"]
                _OVF[0] = False
                new[n] = (self._arith(e, r, g) if nm == "arithmetic-combinator"
                          else self._decider(e, r, g) if nm == "decider-combinator" else self._selector(e, r, g))
                if _OVF[0]:
                    self.ovf[n] = nm
                else:
                    self.ovf.pop(n, None)
            changed_nets = set()
            for n, v in new.items():
                if v != self.out[n]:
                    self.out[n] = v
                    for cid in (RED_OUT, GREEN_OUT):
                        net = self.net_of.get((n, cid))
                        if net is not None:
                            changed_nets.add(net)
            self.dirty = set()
            for net in changed_nets:
                self._recompute(net)
                self.dirty |= self.readers[net]
            self.tick += 1

    def settle(self, max_ticks=500):
        for t in range(max_ticks):
            if not self.dirty:
                return t
            self.step()
        raise RuntimeError("did not settle")

    def net(self, n, cid):
        return dict(self.netval.get(self.net_of.get((n, cid)), {}))
