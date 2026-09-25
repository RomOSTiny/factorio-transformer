"""
Exports demo_weights.json (trained by demo_train.py) into a Factorio
blueprint: 4 input signals -> 2 ReLU hidden neurons -> 3 output classes ->
argmax via pairwise-comparison Decider combinators. See ../PROJECT.md for
the design and decision log.

Argmax used to be one Selector combinator in "select max" mode - abandoned
after extensive live debugging (three independently-sourced configurations,
including the schema straight from the game's own bundled runtime-api.json,
all produced empty output with no error). Root cause never confirmed; the
live-script tests meant to isolate it were themselves compromised by an
unrelated Lua `.` vs `:` method-call bug, so the Selector combinator itself
was never conclusively cleared or convicted. Not worth chasing further -
pairwise-max via Decider combinators (multi-condition AND, a documented
and already-proven-working 2.0 feature here, see the ReLU fix) achieves the
same result with entity types already confirmed reliable in this project.

Fixed-point: weights/biases are scaled by SCALE and rounded to int, since
circuit signals are integers. Argmax only cares about relative order, so
this tiny 2-layer net doesn't need a rescale-divide between layers (the
compounded scale stays far under int32 range) - a deeper/full version would
need explicit rescaling to avoid overflow, noted here for later.
"""

import json

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import (
    ArithmeticCombinator,
    ConstantCombinator,
    DeciderCombinator,
    ElectricEnergyInterface,
    ElectricPole,
)

SCALE = 1000

with open("demo_weights.json") as f:
    weights = json.load(f)

KEYWORDS = weights["keywords"]
CLASSES = weights["classes"]
W1 = weights["W1"]
b1 = weights["b1"]
W2 = weights["W2"]
b2 = weights["b2"]

INPUT_SIGNALS = ["signal-A", "signal-B", "signal-C", "signal-D"]
HIDDEN_PRE_SIGNALS = ["signal-E", "signal-F"]
# Decider's "copy count from input" looks up the count of a signal with the
# SAME NAME as the output on the input side - it does NOT pass through
# whatever the condition matched under a new name (confirmed via Factorio
# forums - a known 2.0 gotcha). So post-ReLU must reuse the pre-activation
# signal name. Safe to reuse: decider input/output are separate physical
# wire networks here (output is never wired back into its own input), so
# there's no feedback loop despite the shared name.
HIDDEN_SIGNALS = HIDDEN_PRE_SIGNALS
OUTPUT_SIGNALS = ["signal-0", "signal-1", "signal-2"]

# Demo test input: only "how" (index 2) is present -> should classify as "question"
TEST_INPUT = [0, 0, 1, 0]

bp = Blueprint()
bp.label = "demo classifier (hello/bye/how/you -> greeting/farewell/question)"


def q(x):
    return int(round(x * SCALE))


entities = []


def add(entity):
    entities.append(entity)
    return entity


# --- Input layer: 4 constant combinators, one flag per keyword ---
# Layout kept compact throughout: max wire connection distance is 9 tiles
# (confirmed via research, see PROJECT.md), so every producer->consumer pair
# below is placed well under that, not just the overall block.
for i, sig in enumerate(INPUT_SIGNALS):
    c = ConstantCombinator(id=f"in_{i}", tile_position=(i, 0))
    c.set_signal(index=0, name=sig, count=TEST_INPUT[i])
    add(c)

# --- Hidden layer: 2 neurons, each = 4 weighted inputs + bias, then ReLU ---
for j in range(2):
    row_y = 3 + j * 2  # rows 2 tiles apart, both still close to the input row
    for i in range(4):
        ac = ArithmeticCombinator(
            id=f"h{j}_w{i}",
            tile_position=(i, row_y),
            first_operand=INPUT_SIGNALS[i],
            operation="*",
            second_operand=q(W1[i][j]),
            output_signal=HIDDEN_PRE_SIGNALS[j],
        )
        add(ac)
    bias = ConstantCombinator(id=f"h{j}_bias", tile_position=(4, row_y))
    bias.set_signal(index=0, name=HIDDEN_PRE_SIGNALS[j], count=q(b1[j]))
    add(bias)

    relu = DeciderCombinator(
        id=f"h{j}_relu",
        tile_position=(5, row_y),
        conditions=[DeciderCombinator.Condition(first_signal=HIDDEN_PRE_SIGNALS[j], comparator=">=", constant=0)],
        outputs=[DeciderCombinator.Output(signal=HIDDEN_SIGNALS[j], copy_count_from_input=True)],
    )
    add(relu)

# --- Output layer: 3 classes, each = 2 weighted hidden activations + bias ---
OUTPUT_ROW_Y = 8  # close to both hidden rows (y=3 and y=5)
for k in range(3):
    for j in range(2):
        ac = ArithmeticCombinator(
            id=f"o{k}_w{j}",
            tile_position=(k * 3 + j, OUTPUT_ROW_Y),
            first_operand=HIDDEN_SIGNALS[j],
            operation="*",
            second_operand=q(W2[j][k]),
            output_signal=OUTPUT_SIGNALS[k],
        )
        add(ac)
    bias = ConstantCombinator(id=f"o{k}_bias", tile_position=(k * 3 + 2, OUTPUT_ROW_Y))
    bias.set_signal(index=0, name=OUTPUT_SIGNALS[k], count=q(b2[k]))
    add(bias)

# --- Argmax over the 3 output class signals, via pairwise comparison ---
# class k wins if its score beats every other class - >= against lower
# indices, > against higher indices, so exactly one class wins even on an
# exact tie (first index wins).
WINNER_SIGNALS = ["signal-G", "signal-H", "signal-I"]
ARGMAX_ROW_Y = OUTPUT_ROW_Y + 2
for k in range(3):
    conditions = []
    for other in range(3):
        if other == k:
            continue
        comparator = ">=" if other > k else ">"
        conditions.append(
            DeciderCombinator.Condition(
                first_signal=OUTPUT_SIGNALS[k],
                comparator=comparator,
                second_signal=OUTPUT_SIGNALS[other],
                compare_type="and",
            )
        )
    winner = DeciderCombinator(
        id=f"argmax_{k}",
        tile_position=(k, ARGMAX_ROW_Y),
        conditions=conditions,
        outputs=[DeciderCombinator.Output(signal=WINNER_SIGNALS[k], copy_count_from_input=False, constant=1)],
    )
    add(winner)

# --- Power, baked in - no manual placement needed ---
# Substation supply_area_distance=9 tiles (checked against draftsman's
# entity data) covers this whole ~9x11 tile layout from one point (worst
# case corner is ~8.6 tiles away). Placed in column x=7, which is clear of
# every other entity's real footprint (arithmetic/decider/selector are
# 0.7x1.3 tiles, not 1x1 - checked via draftsman.data.entities, that's what
# caused the first collision attempt at (4,6)).
# electric-energy-interface must be named explicitly - the draftsman
# default resolves to "hidden-electric-energy-interface" (a different,
# not-power-connectable debug variant) - and it only holds/produces energy,
# it has no supply_area_distance of its own, so it still needs a pole/
# substation wired to it to actually distribute that power.
eei = ElectricEnergyInterface(
    name="electric-energy-interface", id="power_source", tile_position=(7, 0), buffer_size=10**9
)
add(eei)
substation = ElectricPole(name="substation", id="power_relay", tile_position=(7, 3))
add(substation)

for e in entities:
    bp.entities.append(e)

# --- Wiring ---
RED = "red"

# inputs -> hidden weight multipliers
for j in range(2):
    for i in range(4):
        bp.add_circuit_connection(RED, f"in_{i}", f"h{j}_w{i}", side_2="input")

# hidden weight multipliers + bias -> relu input
for j in range(2):
    for i in range(4):
        bp.add_circuit_connection(RED, f"h{j}_w{i}", f"h{j}_relu", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"h{j}_bias", f"h{j}_relu", side_2="input")

# relu output -> output-layer weight multipliers
for j in range(2):
    for k in range(3):
        bp.add_circuit_connection(RED, f"h{j}_relu", f"o{k}_w{j}", side_1="output", side_2="input")

# output weight multipliers + bias -> each argmax decider's input (all 3
# need to see all 3 class scores, not just their own)
for winner_idx in range(3):
    for k in range(3):
        for j in range(2):
            bp.add_circuit_connection(RED, f"o{k}_w{j}", f"argmax_{winner_idx}", side_1="output", side_2="input")
        bp.add_circuit_connection(RED, f"o{k}_bias", f"argmax_{winner_idx}", side_2="input")

# draftsman's add_power_connection rejects electric-energy-interface as
# "not power connectable" (a draftsman limitation, not a game one) - the
# two are 3 tiles apart, well within the substation's 18-tile wire reach,
# so relying on Factorio's normal auto-connect-on-construction behavior
# for power-network entities placed near each other instead.

blueprint_string = bp.to_string()

with open("demo_blueprint.txt", "w") as f:
    f.write(blueprint_string)

print(f"Entities: {len(entities)}")
print(f"Test input: {dict(zip(KEYWORDS, TEST_INPUT))}")

# sanity check in Python, same math the combinators will do
import numpy as np

x = np.array(TEST_INPUT, dtype=np.float64)
h = np.maximum(0, x @ np.array(W1) + np.array(b1))
logits = h @ np.array(W2) + np.array(b2)
winner_idx = int(np.argmax(logits))
pred = CLASSES[winner_idx]
print(f"Expected winner: {pred} (logits={logits.round(3).tolist()})")
print(f"Expect winning signal in-game: {WINNER_SIGNALS[winner_idx]} (only this one, count=1)")
print("\nSaved demo_blueprint.txt")
