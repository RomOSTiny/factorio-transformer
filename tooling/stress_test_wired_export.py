"""
Same idea as stress_test_export.py, but with REAL circuit-network load
instead of isolated no-op combinators. Groups of 4 arithmetic combinators
share one local constant-combinator input (a real non-zero signal) and all
4 sum onto the SAME output signal - real wire-based signal propagation and
summation, matching exactly how the actual classifier's neurons work
(multiple weighted terms summing on a shared wire). The previous test only
measured raw per-entity evaluation cost with nothing actually flowing
through any wire.

Layout: a grid of "group slots" (world x = col*GROUP_WIDTH, y = row*SPACING).
Every SUBSTATION_SPACING_UNITS-th row/col, a substation takes over the slot
instead of a group - same "cell is either A or B, never both" trick that
avoided all collision math in stress_test_export.py, just applied to group
slots instead of individual combinators.

Usage: reads N (target arithmetic-combinator count) from sys.argv, writes
stress_test_wired_N.txt
"""

import math
import sys

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, ElectricEnergyInterface, ElectricPole

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
GROUP_SIZE = 4  # 4 arithmetic combinators summing onto one shared signal, per group
GROUP_WIDTH = 6  # tiles: 1 constant + 4 arithmetic + 1 gap, all well under 9-tile wire reach
SPACING = 2  # tiles between group rows
# Rows are SPACING(2) tiles apart, columns are GROUP_WIDTH(6) tiles apart -
# different scales, so substation spacing needs separate unit counts per
# axis to land on the same ~12-tile real distance both ways (first attempt
# used one constant for both and put substations 36 tiles apart in x -
# ConnectionDistanceWarning caught it, fixed here).
SUBSTATION_ROW_UNITS = 6  # 6 * SPACING(2) = 12 tiles
SUBSTATION_COL_UNITS = 2  # 2 * GROUP_WIDTH(6) = 12 tiles

n_groups = math.ceil(N / GROUP_SIZE)
side = math.ceil(math.sqrt(n_groups) * 1.15) + SUBSTATION_ROW_UNITS

bp = Blueprint()
bp.label = f"UPS stress test (wired) - {N} arithmetic combinators, {n_groups} groups"

entities = []


def add(e):
    entities.append(e)
    return e


def is_substation_cell(row, col):
    return row % SUBSTATION_ROW_UNITS == 0 and col % SUBSTATION_COL_UNITS == 0


count = 0
group_idx = 0
sub_count = 0
lattice = {}
group_positions = []  # (group_idx, x, y) for wiring pass afterwards

for row in range(side):
    if group_idx >= n_groups:
        break
    for col in range(side):
        if group_idx >= n_groups:
            break
        x, y = col * GROUP_WIDTH, row * SPACING
        if is_substation_cell(row, col):
            sub_id = f"sub_{sub_count}"
            add(ElectricPole(name="substation", id=sub_id, tile_position=(x, y)))
            lattice[(row // SUBSTATION_ROW_UNITS, col // SUBSTATION_COL_UNITS)] = sub_id
            sub_count += 1
        else:
            in_id = f"gin_{group_idx}"
            const = ConstantCombinator(id=in_id, tile_position=(x, y))
            const.set_signal(index=0, name="signal-A", count=7)  # arbitrary real non-zero value
            add(const)
            n_in_group = min(GROUP_SIZE, N - count)
            for k in range(n_in_group):
                ac = ArithmeticCombinator(
                    id=f"g{group_idx}_a{k}",
                    tile_position=(x + 1 + k, y),
                    first_operand="signal-A",
                    operation="*",
                    second_operand=count + 1,
                    output_signal="signal-B",  # same signal for all 4 -> real summation on the shared wire
                )
                add(ac)
                count += 1
            group_positions.append((group_idx, n_in_group))
            group_idx += 1

for e in entities:
    bp.entities.append(e)

# wiring: each group's constant -> its own arithmetic combinators (real signal read)
for g, n_in_group in group_positions:
    in_id = f"gin_{g}"
    for k in range(n_in_group):
        bp.add_circuit_connection("red", in_id, f"g{g}_a{k}", side_2="input")

# substation mesh - proximity alone does NOT auto-connect a whole lattice
# (confirmed empirically on the unwired test), needs explicit wiring
wired = 0
for (r, c), sub_id in lattice.items():
    for nr, nc in ((r, c + 1), (r + 1, c)):
        neighbor_id = lattice.get((nr, nc))
        if neighbor_id:
            bp.add_power_connection(sub_id, neighbor_id)
            wired += 1

eei = ElectricEnergyInterface(
    name="electric-energy-interface", id="power_source", tile_position=(-3, 0), buffer_size=10**9
)
bp.entities.append(eei)

blueprint_string = bp.to_string()
fname = f"stress_test_wired_{N}.txt"
with open(fname, "w") as f:
    f.write(blueprint_string)

print(f"N={N}: {count} arithmetic combinators in {group_idx} groups (real wired sum, {sub_count} substations, {wired} power mesh links)")
print(f"Total entities: {len(entities) + 1}")
print(f"Saved {fname}")
