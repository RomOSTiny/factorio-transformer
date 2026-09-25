"""
Isolated test of JUST the pulse + AND-gated accumulator mechanism used in
stage2_matmul_test_export.py's gate_j - decoupled from all ROM/padding
complexity, to find out whether this specific piece is sound at all.

Should have been built FIRST per the project's own established method
(Reshenie 21: small demo before integrating into something complex) -
skipped that step this time and paid for it with hours of debugging a
much bigger structure. Fixing that now.

Design: t_ctr free-runs. addr = t_ctr // K (small K, fast to observe).
tmod = t_ctr % K. pulse fires when tmod == K-1 (last tick of each
address). A trivial "value" signal-V is just addr itself (so we know
exactly what SHOULD be captured: acc should hold sum(0,1,2,...,N-1) =
N*(N-1)/2 once addr exceeds the valid range and holds forever after).
gate condition: signal-A(addr, used as a stand-in "which slot" signal,
constant 0 - i.e. always "select slot 0") == 0 AND tmod == K-1 - this
is the EXACT same two-condition AND pattern as gate_j, just applied to
every single address (not gated on a specific output index) so ALL N
values get summed into ONE accumulator, giving an easily-computed
expected total to check against.
"""

import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

K = 100  # ticks per address - long enough to comfortably observe manually
N = 10  # number of addresses to sweep (0..N-1)
RED, GREEN = "red", "green"

bp = Blueprint()
bp.label = "pulse+AND-gate isolated test"

t_ctr = ArithmeticCombinator(id="t_ctr", position=(0.5, 1.0), first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T")
bp.entities.append(t_ctr)
bp.add_circuit_connection(RED, "t_ctr", "t_ctr", side_1="output", side_2="input")

addr = ArithmeticCombinator(id="addr", position=(0.5, 4.0), first_operand="signal-T", operation="/", second_operand=K, output_signal="signal-D")
bp.entities.append(addr)
bp.add_circuit_connection(RED, "t_ctr", "addr", side_1="output", side_2="input")

tmod = ArithmeticCombinator(id="tmod", position=(3.5, 1.0), first_operand="signal-T", operation="%", second_operand=K, output_signal="signal-M")
bp.entities.append(tmod)
bp.add_circuit_connection(RED, "t_ctr", "tmod", side_1="output", side_2="input")

# merge addr(signal-D) and tmod(signal-M) onto one GREEN network, same
# pattern as o_merge in the real script
merge = ArithmeticCombinator(id="merge", position=(3.5, 4.0), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(merge)
bp.add_circuit_connection(GREEN, "addr", "merge", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "tmod", "merge", side_1="output", side_2="input")

# gate: fires exactly once per address (when tmod==K-1), passing signal-D
# (=addr, i.e. the CURRENT address value) through as signal-V
gate = DeciderCombinator(
    id="gate", position=(6.5, 4.0),
    conditions=[
        DeciderCombinator.Condition(first_signal="signal-M", comparator="=", constant=K - 1, compare_type="and"),
    ],
    outputs=[DeciderCombinator.Output(signal="signal-V", copy_count_from_input=False, constant=1)],
)
bp.entities.append(gate)
bp.add_circuit_connection(GREEN, "merge", "gate", side_1="output", side_2="input")

# acc: += 1 every time the pulse fires (should end up exactly N after the
# full sweep, then hold forever - simplest possible thing to check,
# doesn't even need signal-D's value, just "did the gate fire exactly N
# times")
acc = ArithmeticCombinator(id="acc", position=(6.5, 7.0), first_operand="signal-A", operation="+", second_operand="signal-V", output_signal="signal-A")
bp.entities.append(acc)
bp.add_circuit_connection(RED, "acc", "acc", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "gate", "acc", side_1="output", side_2="input")

# ---- second part: EXACT two-condition AND pattern from gate_j (signal-
# "which slot" == k AND signal-M == K-1), not yet covered by the single-
# condition test above. slot = addr % 3, merged in alongside D/M so all
# three (D, M, S) travel together - 3 gates, 3 accumulators, one per slot.
slot = ArithmeticCombinator(id="slot", position=(0.5, 7.0), first_operand="signal-D", operation="%", second_operand=3, output_signal="signal-S")
bp.entities.append(slot)
bp.add_circuit_connection(RED, "addr", "slot", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "slot", "merge", side_1="output", side_2="input")

for k in range(3):
    gk = DeciderCombinator(
        id=f"gate2_{k}", position=(0.5 + k * 3, 11.0),
        conditions=[
            DeciderCombinator.Condition(first_signal="signal-S", comparator="=", constant=k, compare_type="and"),
            DeciderCombinator.Condition(first_signal="signal-M", comparator="=", constant=K - 1, compare_type="and"),
        ],
        outputs=[DeciderCombinator.Output(signal="signal-V", copy_count_from_input=False, constant=1)],
    )
    bp.entities.append(gk)
    bp.add_circuit_connection(GREEN, "merge", f"gate2_{k}", side_1="output", side_2="input")
    ak = ArithmeticCombinator(id=f"acc2_{k}", position=(0.5 + k * 3, 14.0), first_operand="signal-A", operation="+", second_operand="signal-V", output_signal="signal-A")
    bp.entities.append(ak)
    bp.add_circuit_connection(RED, f"acc2_{k}", f"acc2_{k}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"gate2_{k}", f"acc2_{k}", side_1="output", side_2="input")

# power - legendary poles for their much larger supply/wire radius (plain
# medium-pole's supply area is too small to reach this now-15-entity,
# y=0..14 spread from a single pole - found the hard way on the smaller
# 8-entity version, fixed proactively here).
eei = ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=(10, 1), buffer_size=10**9)
bp.entities.append(eei)
for i, py in enumerate((3, 8, 13)):
    p = ElectricPole(name="medium-electric-pole", id=f"pole{i}", position=(4, py), quality="legendary")
    bp.entities.append(p)
bp.add_power_connection("pole0", "pole1")
bp.add_power_connection("pole1", "pole2")

blueprint_string = bp.to_string()
with open("pulse_gate_isolated_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)

print(f"Entities: {len(bp.entities)}")
print(f"K={K}, N={N}, full sweep = {N*K} ticks = {N*K/60:.1f} sec")
print(f"Expected: acc (signal-A) = {N} after settle (gate fires once per address, N addresses)")
print("Saved pulse_gate_isolated_test_blueprint.txt")
