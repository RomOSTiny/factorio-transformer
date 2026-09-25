"""Isolated live test of the Factorio 2.0 combinator features the dense attention relies on.

Each sub-test has its own networks and a known expected result:
  a  dot product      each(red) * each(green) -> S          (V=1 * V=1000 adds the offset)
  b  vector * scalar  each(green) * W(red) -> each          (red A must NOT leak in)
  c  exp step bank    each <= thr -> each = delta, 2 deciders summed on one network
  d  max              selector (select max, index 0) -> each + 0 -> M
  e  scalar - vector  M(red) - each(green) -> each
  f  vector / scalar  each(green) / S(red) -> each
  g  KV cache cells   sample-and-hold: gate "W==n -> copy green", hold "W!=n AND R==0 ->
                      copy green" with a green self-loop; two cells (n=1, n=2), driven by RCON
  h  pole relay       constant -> medium pole -> big pole (~25 tiles) -> combinator
Outputs are read by attn_prims_live.py.
"""
import json
import warnings

caught = []
warnings.showwarning = lambda m, *a, **k: caught.append(str(m))

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import (ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface,
                              ElectricPole, SelectorCombinator)

R, G = "red", "green"
EACH = "signal-each"
EVERYTHING = "signal-everything"   # decider output "each" is dropped by the game unless "each" is in a condition
bp = Blueprint()
bp.label = "attn prims test"
expect = {}


def const(eid, pos, sigs):
    c = ConstantCombinator(id=eid, tile_position=pos)
    for k, (name, v) in enumerate(sigs.items()):
        c.set_signal(index=k, name=name, count=v)
    bp.entities.append(c)
    return eid


def arith(eid, pos, **kw):
    bp.entities.append(ArithmeticCombinator(id=eid, tile_position=pos, **kw))
    return eid


def decider(eid, pos, conditions, outputs):
    bp.entities.append(DeciderCombinator(id=eid, tile_position=pos, conditions=conditions, outputs=outputs))
    return eid


def cond(sig, cmp, const_v, nets=(R, G), ct="or"):
    return DeciderCombinator.Condition(first_signal=sig, first_signal_networks=set(nets), comparator=cmp,
                                       constant=const_v, compare_type=ct)


def wire(color, a, b, s1=None, s2=None):
    kw = {}
    if s1:
        kw["side_1"] = s1
    if s2:
        kw["side_2"] = s2
    bp.add_circuit_connection(color, a, b, **kw)


def sink(eid, pos, src, color=R):
    const(eid, pos, {})
    wire(color, src, eid, s1="output")


# a: dot product with offset
X = 0
const("a_r", (X, 0), {"signal-A": 3, "signal-B": -4, "signal-C": 5, "signal-V": 1})
const("a_g", (X + 2, 0), {"signal-A": 2, "signal-B": 6, "signal-C": -1, "signal-D": 7, "signal-V": 1000})
arith("a_ar", (X + 1, 2), first_operand=EACH, operation="*", second_operand=EACH, output_signal="signal-S",
      first_operand_wires={R}, second_operand_wires={G})
wire(R, "a_r", "a_ar", s2="input")
wire(G, "a_g", "a_ar", s2="input")
sink("a_sink", (X + 1, 5), "a_ar")
expect["a"] = {"signal-S": 6 - 24 - 5 + 1000}

# b: vector * scalar (each green * W red)
X = 6
const("b_r", (X, 0), {"signal-W": 5, "signal-A": 100})
const("b_g", (X + 2, 0), {"signal-A": 3, "signal-B": -4})
arith("b_ar", (X + 1, 2), first_operand=EACH, operation="*", second_operand="signal-W", output_signal=EACH,
      first_operand_wires={G}, second_operand_wires={R})
wire(R, "b_r", "b_ar", s2="input")
wire(G, "b_g", "b_ar", s2="input")
sink("b_sink", (X + 1, 5), "b_ar")
expect["b"] = {"signal-A": 15, "signal-B": -20}

# c: exp step bank
X = 12
const("c_g", (X, 0), {"signal-A": 1, "signal-B": 8, "signal-C": 9, "signal-D": 100})
decider("c_d1", (X + 1, 2), [cond(EACH, "<=", 8)], [DeciderCombinator.Output(signal=EACH, copy_count_from_input=False, constant=7)])
decider("c_d2", (X + 2, 2), [cond(EACH, "<=", 16)], [DeciderCombinator.Output(signal=EACH, copy_count_from_input=False, constant=5)])
wire(G, "c_g", "c_d1", s2="input")
wire(G, "c_d1", "c_d2", s1="input", s2="input")
wire(R, "c_d1", "c_d2", s1="output", s2="output")
sink("c_sink", (X + 1, 5), "c_d1")
expect["c"] = {"signal-A": 12, "signal-B": 12, "signal-C": 5}

# d: max via selector, then each + 0 -> M
X = 18
const("d_g", (X, 0), {"signal-A": 5, "signal-B": 17, "signal-C": -3})
bp.entities.append(SelectorCombinator(id="d_sel", tile_position=(X + 1, 2), operation="select", select_max=True, index_constant=0))
arith("d_m", (X + 2, 2), first_operand=EACH, operation="+", second_operand=0, output_signal="signal-M")
wire(G, "d_g", "d_sel", s2="input")
wire(R, "d_sel", "d_m", s1="output", s2="input")
sink("d_sink", (X + 2, 5), "d_m")
expect["d_sel"] = {"signal-B": 17}
expect["d"] = {"signal-M": 17}

# e: scalar(red) - each(green)
X = 24
const("e_r", (X, 0), {"signal-M": 18})
const("e_g", (X + 2, 0), {"signal-A": 5, "signal-B": 17})
arith("e_ar", (X + 1, 2), first_operand="signal-M", operation="-", second_operand=EACH, output_signal=EACH,
      first_operand_wires={R}, second_operand_wires={G})
wire(R, "e_r", "e_ar", s2="input")
wire(G, "e_g", "e_ar", s2="input")
sink("e_sink", (X + 1, 5), "e_ar")
expect["e"] = {"signal-A": 13, "signal-B": 1}

# f: each(green) / S(red)
X = 30
const("f_r", (X, 0), {"signal-S": 3})
const("f_g", (X + 2, 0), {"signal-A": 700, "signal-B": 300})
arith("f_ar", (X + 1, 2), first_operand=EACH, operation="/", second_operand="signal-S", output_signal=EACH,
      first_operand_wires={G}, second_operand_wires={R})
wire(R, "f_r", "f_ar", s2="input")
wire(G, "f_g", "f_ar", s2="input")
sink("f_sink", (X + 1, 5), "f_ar")
expect["f"] = {"signal-A": 233, "signal-B": 100}

# g: two sample-and-hold KV cells on shared control (red) and data (green)
X = 36
const("g_ctl", (X, 0), {})
const("g_data", (X + 1, 0), {"signal-A": 11, "signal-B": 22})
for n, y in ((1, 2), (2, 6)):
    gate, hold = f"g_gate{n}", f"g_hold{n}"
    decider(gate, (X, y), [cond("signal-W", "=", n, nets=(R,))],
            [DeciderCombinator.Output(signal=EVERYTHING, copy_count_from_input=True, networks={G})])
    decider(hold, (X + 1, y), [cond("signal-W", "!=", n, nets=(R,)), cond("signal-R", "=", 0, nets=(R,), ct="and")],
            [DeciderCombinator.Output(signal=EVERYTHING, copy_count_from_input=True, networks={G})])
    wire(G, gate, hold, s1="output", s2="input")
    wire(G, hold, hold, s1="output", s2="input")
    wire(R, gate, hold, s1="input", s2="input")
wire(R, "g_ctl", "g_gate1", s2="input")
wire(G, "g_data", "g_gate1", s2="input")
wire(R, "g_gate1", "g_gate2", s1="input", s2="input")
wire(G, "g_gate1", "g_gate2", s1="input", s2="input")

# h: pole relay chain (red), ~25 tiles
X = 44
const("h_src", (X, 0), {"signal-A": 5})
bp.entities.append(ElectricPole(name="medium-electric-pole", id="h_p1", tile_position=(X + 6, 0)))
bp.entities.append(ElectricPole(name="big-electric-pole", id="h_p2", tile_position=(X + 12, 0)))
bp.entities.append(ElectricPole(name="big-electric-pole", id="h_p3", tile_position=(X + 36, 0)))
arith("h_ar", (X + 38, 2), first_operand=EACH, operation="*", second_operand=1, output_signal=EACH)
wire(R, "h_src", "h_p1")
wire(R, "h_p1", "h_p2")
wire(R, "h_p2", "h_p3")
wire(R, "h_p3", "h_ar", s2="input")
sink("h_sink", (X + 38, 5), "h_ar")
expect["h"] = {"signal-A": 5}

# power: two substation rows
SUB_X = list(range(0, 90, 12))
for row_y in (-4, 9):
    for x in SUB_X:
        bp.entities.append(ElectricPole(name="substation", id=f"sub_{row_y}_{x}", tile_position=(x, row_y), quality="legendary"))
for x0, x1 in zip(SUB_X, SUB_X[1:]):
    bp.add_power_connection(f"sub_-4_{x0}", f"sub_-4_{x1}")
    bp.add_power_connection(f"sub_9_{x0}", f"sub_9_{x1}")
bp.add_power_connection("sub_-4_0", "sub_9_0")
bp.entities.append(ElectricEnergyInterface(name="electric-energy-interface", id="power_source", tile_position=(3, -4), buffer_size=10 ** 9))

bp_string = bp.to_string()
idmap = [{"id": e.id, "x": round(e.position.x, 3), "y": round(e.position.y, 3), "name": e.name} for e in bp.entities if getattr(e, "id", None)]
open("attn_prims_blueprint.txt", "w").write(bp_string)
json.dump(dict(ids=idmap, expect=expect), open("attn_prims_ids.json", "w"), indent=1)
xs = [e["x"] for e in idmap]; ys = [e["y"] for e in idmap]
print("entities", len(bp.entities), "bbox", min(xs), max(xs), min(ys), max(ys), "center", (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
print("warnings", len(caught))
for w in caught:
    print("  ", w[:220])
