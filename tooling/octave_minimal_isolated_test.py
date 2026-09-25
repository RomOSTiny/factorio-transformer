"""
Truly minimal isolated test: does o_collect stay stable at 1, or does it
grow, for the SIMPLEST possible version of the mechanism (one fixed,
never-changing value; one comparator; one collect relay renaming to
signal-O)? The redesigned collector (proven relay-chain pattern, matching
build_addressed_rom's col_collectors) gave the IDENTICAL 2^(address index)
growth bug as the original output-output daisy chain - ruling out collector
TOPOLOGY as the cause. This strips away everything else (broadcast spine,
ROM addressing, address sweep, gates/accumulators) to find out if even the
most basic single-comparator case is stable, isolating whether the bug is
in "many comparators interacting" or in something more fundamental (signal
naming, "signal-each" passthrough behavior, etc).
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "minimal single-comparator stability test"

# fixed value, never changes - if o_collect grows over time even here,
# the bug has nothing to do with address changes or multiple comparators
src = ConstantCombinator(id="src", tile_position=(0, 0))
src.set_signal(index=0, name="signal-V", count=10)
bp.entities.append(src)

# a short relay chain (3 hops), same "signal-each" passthrough bridge()
# uses everywhere else in this project - tests whether the broadcast
# relay mechanism itself is the culprit, not just the comparator/collector
relay_positions = [(3, 0), (6, 0), (9, 0)]
prev_id = "src"
for i, pos in enumerate(relay_positions):
    rid = f"relay_{i}"
    e = ArithmeticCombinator(id=rid, position=(pos[0] + 0.5, pos[1] + 1.0), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(e)
    if prev_id == "src":
        bp.add_circuit_connection(RED, prev_id, rid, side_2="input")  # ConstantCombinator has only one port, no side_1
    else:
        bp.add_circuit_connection(RED, prev_id, rid, side_1="output", side_2="input")
    prev_id = rid
bc_end = prev_id

cmp_e = DeciderCombinator(
    id="cmp_0", position=(12.5, 1.0),
    conditions=[DeciderCombinator.Condition(first_signal="signal-V", comparator=">=", constant=2)],
    outputs=[DeciderCombinator.Output(signal="signal-I", copy_count_from_input=False, constant=1)],
)
bp.entities.append(cmp_e)
bp.add_circuit_connection(RED, bc_end, "cmp_0", side_1="output", side_2="input")

collect_e = ArithmeticCombinator(id="collect_0", position=(12.5, 4.0), first_operand="signal-I", operation="*", second_operand=1, output_signal="signal-I")
bp.entities.append(collect_e)
bp.add_circuit_connection(RED, "cmp_0", "collect_0", side_1="output", side_2="input")

o_collect = ArithmeticCombinator(id="o_collect", position=(15.5, 4.0), first_operand="signal-I", operation="+", second_operand=0, output_signal="signal-O")
bp.entities.append(o_collect)
bp.add_circuit_connection(RED, "collect_0", "o_collect", side_1="output", side_2="input")

eei = ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=(2, 1), buffer_size=10**9)
bp.entities.append(eei)
for i, py in enumerate((1, 4, 7)):
    p = ElectricPole(name="medium-electric-pole", id=f"pole{i}", position=(6, py), quality="legendary")
    bp.entities.append(p)
pole3 = ElectricPole(name="medium-electric-pole", id="pole3", position=(15, 4), quality="legendary")  # near
# o_collect (local 15.5,4.0) - the original 3-pole row at x=6 never reached
# out to x=15.5 (o_collect.electric_network_id came back "none" live).
bp.entities.append(pole3)
# NOT bp.add_power_connection("power_source", "pole0") - draftsman itself
# rejects that (EntityNotPowerConnectableError: electric-energy-interface).
# Every OTHER script in this project (stage2_matmul_test_export.py etc.)
# never wires EEI explicitly either - it auto-links to any pole/substation
# within its own connection RANGE just by being placed close enough, no
# wire call needed. Found live why THIS test's EEI never linked (net="none"
# despite poles correctly showing network 9): position=(-3,1) put it 9
# tiles from pole0 at (6,1), likely just past medium-electric-pole's reach.
# Moved to (2,1), well within range.
bp.add_power_connection("pole0", "pole1")
bp.add_power_connection("pole1", "pole2")
bp.add_power_connection("pole1", "pole3")
bp.add_power_connection("pole1", "pole2")

blueprint_string = bp.to_string()
with open("octave_minimal_isolated_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)
print(f"Entities: {len(bp.entities)}")
print("Saved octave_minimal_isolated_test_blueprint.txt")
