"""
Generates UPS-capacity stress-test blueprints: N arithmetic combinators in
a grid, each independently computing a trivial multiply (own constant
operands, no wiring needed between them - Factorio evaluates every
combinator's operation each tick regardless of whether its inputs are real
signals, per the Gomoku-project finding that combinators cost the same
whether "active" or not - see PROJECT.md). Power is a lattice of
substations (supply_area_distance=9, so spaced 12 tiles apart guarantees
full coverage - worst-case midpoint distance 12*0.707=8.49 < 9) fed by one
electric-energy-interface, relying on Factorio's proximity auto-connect for
power (confirmed working in the real demo blueprint already).

Usage: reads N from sys.argv, writes stress_test_N.txt
"""

import sys

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ElectricEnergyInterface, ElectricPole

N = int(sys.argv[1]) if len(sys.argv) > 1 else 500
SPACING = 2  # tiles between combinators, safe for their 0.7x1.3 footprint
SUBSTATION_SPACING_UNITS = 6  # 6 * SPACING(2) = 12 tiles between substations

bp = Blueprint()
bp.label = f"UPS stress test - {N} arithmetic combinators"

import math

# Grid cells are either a combinator OR a substation (every
# SUBSTATION_SPACING_UNITS-th cell in both row and col), never both in the
# same cell - avoids any position-overlap math, since a substation just
# takes over a cell that would've held a combinator instead of being
# squeezed in between. Slightly inflate the grid side so we still end up
# with >= N actual combinators after substation cells are subtracted.
side = math.ceil(math.sqrt(N) * 1.2) + SUBSTATION_SPACING_UNITS

entities = []


def add(e):
    entities.append(e)
    return e


def is_substation_cell(row, col):
    return row % SUBSTATION_SPACING_UNITS == 0 and col % SUBSTATION_SPACING_UNITS == 0


count = 0
sub_count = 0
# lattice[(sub_row, sub_col)] = entity id, so grid-adjacent substations can
# be wired to each other afterwards - proximity alone did NOT auto-connect
# them (confirmed empirically: stress_test_500 built with every combinator
# unpowered except the one substation directly next to the power source).
# A single direct EEI-to-substation hop DOES auto-connect on its own
# (confirmed working in the real demo blueprint) - it's only the pole-to-
# pole relay across the lattice that needs an explicit wire.
lattice = {}
for row in range(side):
    if count >= N:
        break
    for col in range(side):
        if count >= N:
            break
        pos = (col * SPACING, row * SPACING)
        if is_substation_cell(row, col):
            sub_id = f"sub_{sub_count}"
            add(ElectricPole(name="substation", id=sub_id, tile_position=pos))
            lattice[(row // SUBSTATION_SPACING_UNITS, col // SUBSTATION_SPACING_UNITS)] = sub_id
            sub_count += 1
        else:
            add(
                ArithmeticCombinator(
                    id=f"stress_{count}",
                    tile_position=pos,
                    first_operand="signal-A",  # no source wired - reads as 0, still a real eval every tick
                    operation="*",
                    second_operand=count + 1,
                    output_signal="signal-B",
                )
            )
            count += 1

eei = ElectricEnergyInterface(
    name="electric-energy-interface", id="power_source", tile_position=(-3, 0), buffer_size=10**9
)
add(eei)

for e in entities:
    bp.entities.append(e)

# Wire every substation to its right and below neighbor in the lattice -
# enough to make the whole grid one connected mesh without duplicate edges.
# 12 tiles apart, well within the substation's 18-tile wire reach.
wired = 0
for (r, c), sub_id in lattice.items():
    for nr, nc in ((r, c + 1), (r + 1, c)):
        neighbor_id = lattice.get((nr, nc))
        if neighbor_id:
            bp.add_power_connection(sub_id, neighbor_id)
            wired += 1
print(f"Power mesh: {wired} substation-to-substation connections")

blueprint_string = bp.to_string()
fname = f"stress_test_{N}.txt"
with open(fname, "w") as f:
    f.write(blueprint_string)

print(f"N={N}: {count} arithmetic combinators + {sub_count} substations + 1 power interface = {len(entities)} total entities")
print(f"Grid: {side}x{side} cells, spacing {SPACING} tiles -> footprint ~{side*SPACING}x{side*SPACING} tiles")
print(f"Saved {fname}")
