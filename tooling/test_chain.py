"""
Isolated repro: does a 7-hop signal-each relay chain (identical pattern to
export_full.py's bridge()) correctly propagate a value end to end, with
NOTHING else in the world? Tests the exact hypothesis from the ongoing
debug session - values reach hop 4 but not hop 5+ in the full 2700-entity
build, despite correct wiring/config/distance at every hop.
"""
from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, ElectricPole, ElectricEnergyInterface

bp = Blueprint()
bp.label = "chain propagation test"

src = ConstantCombinator(id="src", position=(0.5, 0.5))
src.set_signal(index=0, name="iron-plate", count=777)
bp.entities.append(src)

N = 8
prev_id = "src"
for i in range(1, N + 1):
    x = i * 7
    y = i * 2
    cid = f"hop_{i}"
    e = ArithmeticCombinator(id=cid, position=(x + 0.5, y + 1.0), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(e)
    if prev_id == "src":
        bp.add_circuit_connection("red", prev_id, cid, side_2="input")
    else:
        bp.add_circuit_connection("red", prev_id, cid, side_1="output", side_2="input")
    prev_id = cid

sub = ElectricPole(name="substation", id="sub", position=(30, 10))
bp.entities.append(sub)
eei = ElectricEnergyInterface(name="electric-energy-interface", id="eei", position=(27, 10), buffer_size=10**9)
bp.entities.append(eei)

with open("test_chain.txt", "w") as f:
    f.write(bp.to_string())
print(f"Entities: {len(bp.entities)}")
print("Saved test_chain.txt - expect iron-plate=777 on EVERY hop_1..hop_8's output")
