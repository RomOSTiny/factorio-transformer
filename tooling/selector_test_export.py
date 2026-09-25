"""
Test whether Selector combinator "select" mode with a runtime index_signal
gives arbitrary random-access addressing (what we'd need for cheap ROM
packing, PROJECT.md Reshenie 13's open question) or whether it's actually
RANK-based (Nth largest/smallest by VALUE, per FFF-384's own wording:
"sorted from biggest to smallest or vice versa") - those are very
different things. Test uses deliberately NON-monotonic values so the two
interpretations give different, distinguishable answers:

  slot 0 -> 50, slot 1 -> 10, slot 2 -> 90, slot 3 -> 30, slot 4 -> 70

If index-addressing is by STORAGE SLOT (what we want): index=2 -> 90.
If index-addressing is by RANK (descending sort: 90,70,50,30,10):
  index=2 -> 50 (the 3rd largest, which happens to be slot 0's value).

These differ for every index except by coincidence, so a single test at
index=2 already disambiguates.
"""

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, SelectorCombinator

VALUES = [50, 10, 90, 30, 70]  # slot -> value, deliberately non-monotonic
TEST_INDEX = 2  # slot-interpretation expects 90, rank-interpretation expects 50

bp = Blueprint()
bp.label = "selector index-mode test"

store = ConstantCombinator(id="store", tile_position=(0, 0))
for i, v in enumerate(VALUES):
    store.set_signal(index=i, name=f"signal-{chr(ord('A') + i)}", count=v)
bp.entities.append(store)

idx_src = ConstantCombinator(id="idx_src", tile_position=(0, 3))
idx_src.set_signal(index=0, name="signal-I", count=TEST_INDEX)
bp.entities.append(idx_src)

sel = SelectorCombinator(
    id="sel", tile_position=(3, 1),
    operation="select",
    index_signal="signal-I",
)
bp.entities.append(sel)

# store's values on RED into selector's data input; index on GREEN into
# selector's index input - separate colors so the index signal doesn't
# pollute the candidate value list (the known forum caveat, and the exact
# same private-vs-broadcast principle from Reshenie 14)
bp.add_circuit_connection("red", "store", "sel", side_2="input")
bp.add_circuit_connection("green", "idx_src", "sel", side_2="input")

# give the selector's output a real consumer, so a script dump can read
# it (Reshenie 5's "terminal node with no wire reads empty" gotcha)
sink = ArithmeticCombinator(
    id="sink", tile_position=(6, 1),
    first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each",
)
bp.entities.append(sink)
bp.add_circuit_connection("red", "sel", "sink", side_1="output", side_2="input")

eei_pos = (0, 6)
sub_pos = (3, 6)
from draftsman.entity import ElectricEnergyInterface, ElectricPole
bp.entities.append(ElectricEnergyInterface(name="electric-energy-interface", id="power_source", tile_position=eei_pos, buffer_size=10**9))
bp.entities.append(ElectricPole(name="substation", id="power_relay", tile_position=sub_pos))

blueprint_string = bp.to_string()
with open("selector_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)

print(f"Entities: {len(bp.entities)}")
print(f"Values by slot: {VALUES}")
print(f"Test index: {TEST_INDEX}")
print(f"If SLOT-addressed (what we want): expect {VALUES[TEST_INDEX]}")
print(f"If RANK-addressed (sorted desc): expect {sorted(VALUES, reverse=True)[TEST_INDEX]}")
print("Saved selector_test_blueprint.txt")
