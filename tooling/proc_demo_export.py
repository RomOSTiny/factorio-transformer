"""
Stage 2 (generative model) - minimal "processor + memory" proof, built BEFORE
any real transformer piece. See ../PROJECT.md, Решение 13.

Question this demo answers: can a small control unit walk a computed address
across ticks, use that SAME address to pull one value out of each of two
small addressable arrays (a "weight ROM" and an "input ROM"), feed both into
ONE reused multiply-accumulate ALU, and land on the right dot product - i.e.
does "ALU + addressable memory" actually work live in this game, not just on
paper (no engine/draftsman precedent was found for reading the SAME physical
read-circuit at 4 different addresses over time, only for one-shot compare
chains like the classifier's argmax).

Deliberately NOT testing here (kept separate, one unknown at a time, same
discipline as Решение 8/11): the Selector-combinator 20-signals/entity
packing trick (PROJECT.md Решение 13 open question) - this demo uses only
the classic, already-proven constant+decider addressed-cell pattern so a
failure can only mean "the control-flow idea itself is broken", not "the
packing trick didn't work".

--- Design ---

Memory cell (weight array, index i, value V):
  store_i = ConstantCombinator{signal-N: -i, signal-W: V}
  read_i  = DeciderCombinator{condition: signal-N == 0, output: signal-W (copy_count_from_input)}
  read_i's input wire carries BOTH store_i's own signals AND the broadcast
  address (signal-N, from `addr`) - Factorio sums same-named signals from
  different sources on one wire, so signal-N on that wire = addr + (-i),
  which is 0 exactly when addr == i (same trick as export_full.py's window
  codes, and the classic addressable-memory-cell forum design). Exactly one
  of the 4 read_i deciders is non-zero at any time, so wiring all 4 outputs
  into one shared bus and summing gives exactly the selected value - no
  separate "collector" combinator needed, same principle as the syllable
  detectors' collector in export_full.py.
  Input array (signal-X instead of signal-W) is the identical pattern,
  standing in for "an activation vector living in addressable memory" -
  a real matmul needs both operands read this way, not just the weights.

Control unit (the "processor" - reused every step, doesn't grow with N):
  t_ctr = free-running tick counter (self-looped, +1 every tick)
  addr  = signal-T // K  (K ticks "dwell time" per address, division combinator)
  tmod  = signal-T % K
  pulse = decider, fires signal-P=1 for exactly 1 tick out of every K (when
          tmod == K-1, i.e. the LAST tick of each dwell window, giving K-1
          ticks for the addressed read + multiply to settle before it's
          captured)

ALU (2 entities, reused for every one of the 4 steps - this is the actual
"processor, not brute force" point of Решение 1):
  mult     = signal-W * signal-X -> signal-R
  acc_gate = decider, passes signal-R through only during the pulse tick
             (else 0) - without this, acc would re-add the same steady
             product every tick of the K-tick dwell window, not once
  acc      = self-looped accumulator, signal-A += signal-R (gated)

No stop condition needed: once addr runs past the last valid index (>=4),
no cell matches, both buses go to 0, so acc simply stops changing and holds
the final answer forever - self-terminating, no explicit halt logic.
"""

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import (
    ArithmeticCombinator,
    ConstantCombinator,
    DeciderCombinator,
    ElectricEnergyInterface,
    ElectricPole,
)

N = 4  # words in each array
K = 8  # ticks per address step (settling margin over the ~3-tick read delay found in research)

WEIGHTS = [2, -3, 5, 4]
INPUTS = [10, 1, -2, 3]
EXPECTED = sum(w * x for w, x in zip(WEIGHTS, INPUTS))

bp = Blueprint()
bp.label = "stage2 proc-demo: addressed ROM x2 -> reused MAC ALU -> accumulator"

entities = []


def add(entity):
    entities.append(entity)
    return entity


RED = "red"

# --- Control unit ---
# Layout note: decider combinators are 0.7x1.3 tiles (not square) - 1-tile Y
# spacing between two of them overlaps (found by running this script and
# reading draftsman's OverlappingObjectsWarning), so every row below uses
# 2-tile spacing, matching demo_export.py's already-proven "3 + j*2" rows.
t_ctr = add(ArithmeticCombinator(
    id="t_ctr", tile_position=(5, 9),
    first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T",
))
addr = add(ArithmeticCombinator(
    id="addr", tile_position=(5, 3),
    first_operand="signal-T", operation="/", second_operand=K, output_signal="signal-N",
))
tmod = add(ArithmeticCombinator(
    id="tmod", tile_position=(3, 9),
    first_operand="signal-T", operation="%", second_operand=K, output_signal="signal-M",
))
pulse = add(DeciderCombinator(
    id="pulse", tile_position=(1, 9),
    conditions=[DeciderCombinator.Condition(first_signal="signal-M", comparator="=", constant=K - 1)],
    outputs=[DeciderCombinator.Output(signal="signal-P", copy_count_from_input=False, constant=1)],
))

# --- Weight ROM (4 words, classic addressed-cell pattern) ---
for i in range(N):
    store = add(ConstantCombinator(id=f"w_store_{i}", tile_position=(0, 2 * i)))
    store.set_signal(index=0, name="signal-N", count=-i)
    store.set_signal(index=1, name="signal-W", count=WEIGHTS[i])
    add(DeciderCombinator(
        id=f"w_read_{i}", tile_position=(2, 2 * i),
        conditions=[DeciderCombinator.Condition(first_signal="signal-N", comparator="=", constant=0)],
        outputs=[DeciderCombinator.Output(signal="signal-W", copy_count_from_input=True)],
    ))

# --- Input ROM (4 words, same pattern, standing in for addressable activations) ---
for i in range(N):
    store = add(ConstantCombinator(id=f"x_store_{i}", tile_position=(12, 2 * i)))
    store.set_signal(index=0, name="signal-N", count=-i)
    store.set_signal(index=1, name="signal-X", count=INPUTS[i])
    add(DeciderCombinator(
        id=f"x_read_{i}", tile_position=(10, 2 * i),
        conditions=[DeciderCombinator.Condition(first_signal="signal-N", comparator="=", constant=0)],
        outputs=[DeciderCombinator.Output(signal="signal-X", copy_count_from_input=True)],
    ))

# --- ALU: reused every step, doesn't grow with N ---
mult = add(ArithmeticCombinator(
    id="mult", tile_position=(5, 5),
    first_operand="signal-W", operation="*", second_operand="signal-X", output_signal="signal-R",
))
acc_gate = add(DeciderCombinator(
    id="acc_gate", tile_position=(5, 7),
    conditions=[DeciderCombinator.Condition(first_signal="signal-P", comparator="=", constant=1)],
    outputs=[DeciderCombinator.Output(signal="signal-R", copy_count_from_input=True)],
))
acc = add(ArithmeticCombinator(
    id="acc", tile_position=(7, 7),
    first_operand="signal-A", operation="+", second_operand="signal-R", output_signal="signal-A",
))

# --- Power ---
eei = add(ElectricEnergyInterface(
    name="electric-energy-interface", id="power_source", tile_position=(7, 1), buffer_size=10**9
))
substation = add(ElectricPole(name="substation", id="power_relay", tile_position=(7, 4)))

for e in entities:
    bp.entities.append(e)

# --- Wiring ---

# t_ctr self-loop (free-running counter)
bp.add_circuit_connection(RED, "t_ctr", "t_ctr", side_1="output", side_2="input")
# addr and tmod both read the tick counter directly
bp.add_circuit_connection(RED, "t_ctr", "addr", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "t_ctr", "tmod", side_1="output", side_2="input")
# pulse reads tmod
bp.add_circuit_connection(RED, "tmod", "pulse", side_1="output", side_2="input")

# each read_i gets its own store_i (private, signal-N local + signal-W/X
# value) on RED, and the broadcast address (addr's output, signal-N) on
# GREEN - different colors never merge into one network even when they meet
# at the same port, so the 8 stores stay electrically private from each
# other while every read_i still sees addr's value (decider conditions sum
# same-named signals across both colors). First attempt put both on RED,
# which merged all 8 stores + addr into ONE network (confirmed live: every
# store_i read back the SAME sum of all 8 stores' values, not its own) -
# see PROJECT.md Решение 13/14 for the full story.
GREEN = "green"
for i in range(N):
    bp.add_circuit_connection(RED, f"w_store_{i}", f"w_read_{i}", side_2="input")
    bp.add_circuit_connection(GREEN, "addr", f"w_read_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"x_store_{i}", f"x_read_{i}", side_2="input")
    bp.add_circuit_connection(GREEN, "addr", f"x_read_{i}", side_1="output", side_2="input")

# weight bus + input bus -> mult (only one read_i is non-zero at a time, so
# fanning all 4 outputs into mult's input sums to exactly the selected value)
for i in range(N):
    bp.add_circuit_connection(RED, f"w_read_{i}", "mult", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"x_read_{i}", "mult", side_1="output", side_2="input")

# mult + pulse -> acc_gate (gate signal-R through only on the pulse tick)
bp.add_circuit_connection(RED, "mult", "acc_gate", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "pulse", "acc_gate", side_1="output", side_2="input")

# acc: self-loop (holds signal-A) + gated signal-R from acc_gate
bp.add_circuit_connection(RED, "acc", "acc", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "acc_gate", "acc", side_1="output", side_2="input")

blueprint_string = bp.to_string()
with open("proc_demo_blueprint.txt", "w") as f:
    f.write(blueprint_string)

print(f"Entities: {len(entities)}")
print(f"Weights: {WEIGHTS}")
print(f"Inputs:  {INPUTS}")
print(f"Expected dot product (signal-A, after settling): {EXPECTED}")
print(f"Settle time: 4 steps x {K} ticks = {4 * K} ticks minimum before signal-A is final")
print("\nSaved proc_demo_blueprint.txt")
