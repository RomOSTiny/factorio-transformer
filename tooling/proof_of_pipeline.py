"""
Proof-of-pipeline step (see ../PROJECT.md decision log).

Goal: prove that a blueprint generated in Python via factorio-draftsman,
when imported into the real (licensed, Space Age) game, computes the
same result as Python does — before trusting draftsman for a real
classifier network.

Circuit: two constant combinators (signal-A=3, signal-B=5) wired into
one arithmetic combinator computing signal-A * signal-B -> signal-C.
Expected: signal-C = 15 on the arithmetic combinator's output side.
"""

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator

bp = Blueprint()
bp.label = "proof-of-pipeline (3 * 5)"

const_a = ConstantCombinator(id="const_a", tile_position=(0, 0))
const_a.set_signal(index=0, name="signal-A", count=3)

const_b = ConstantCombinator(id="const_b", tile_position=(0, 3))
const_b.set_signal(index=0, name="signal-B", count=5)

mul = ArithmeticCombinator(
    id="mul",
    tile_position=(3, 1),
    first_operand="signal-A",
    operation="*",
    second_operand="signal-B",
    output_signal="signal-C",
)

bp.entities.append(const_a)
bp.entities.append(const_b)
bp.entities.append(mul)

# Reference by id (not the original objects) - EntityList stores its own
# copies, so the original const_a/const_b/mul references go stale on append.
# Both constants ride the same red wire into the combinator's input side;
# signal-A and signal-B are distinct signal names, so they don't collide.
bp.add_circuit_connection("red", "const_a", "mul", side_2="input")
bp.add_circuit_connection("red", "const_b", "mul", side_2="input")

blueprint_string = bp.to_string()

print("Expected result: signal-C = 3 * 5 = 15")
print()
print("Blueprint string (paste into Factorio with Ctrl+V after copying, or import via the blueprint library):")
print(blueprint_string)

with open("proof_of_pipeline_blueprint.txt", "w") as f:
    f.write(blueprint_string)
print()
print("Also saved to proof_of_pipeline_blueprint.txt")
