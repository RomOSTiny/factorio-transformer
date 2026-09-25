"""
Isolated repro for the "systematic missing ROM deciders after revive()"
pattern (LayerNorm + Attention live builds; Решение 36 п.2: rows
{0,4,8,12,16,20} mod 25, IDENTICAL in exp0 & exp1). The generated
blueprint has every decider (verified by decode), so the loss is in
revive(), landing on rows whose y-offset (row*2) coincides with a
vrelay/crelay hop y (multiples of RELAY_HOP=8): rows {0,4,8,...}.

Builds a small ROM (4 full columns, rows_per_col=10 -> 3 hop relays per
column), revives it, reports which t_read_i deciders are missing.
  MODE="orig" - row y = row*2  (verbatim build_addressed_rom)
  MODE="fix"  - row y = row*2 + 1  (rows never share a Y with a hop relay)
No driver/power-consumer - we only measure which read deciders survive.
"""
import math
import sys

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator

MODE = sys.argv[1] if len(sys.argv) > 1 else "orig"
assert MODE in ("orig", "fix")
ROW_DY = 1 if MODE == "fix" else 0

RED, GREEN = "red", "green"
RELAY_HOP = 8
COL_SPACING = 4
ROWS_PER_COL = 25
N_VALUES = 200                      # 8 columns, matches Attention exp ROM
VALUES = [1000 + 7 * i for i in range(N_VALUES)]

bp = Blueprint()
bp.label = f"ROM revive isolated test ({MODE})"


def build_addressed_rom(name, values, cond_signal, out_signal, origin_x, origin_y, rows_per_col=ROWS_PER_COL):
    n = len(values)
    n_cols = math.ceil(n / rows_per_col)
    col_entry = {}
    for col in range(n_cols):
        rows_here = min(rows_per_col, n - col * rows_per_col)
        max_y = (rows_here - 1) * 2
        n_hops = math.ceil(max_y / RELAY_HOP) + 1
        prev_id, y = None, -RELAY_HOP
        hops = []
        for hop in range(n_hops):
            rid = f"{name}_vrelay_{col}_{hop}"
            e = ArithmeticCombinator(id=rid, tile_position=(origin_x + col * COL_SPACING + 1, origin_y + y),
                                     first_operand=cond_signal, operation="*", second_operand=1, output_signal=cond_signal)
            bp.entities.append(e)
            if prev_id is not None:
                bp.add_circuit_connection(GREEN, prev_id, rid, side_1="output", side_2="input")
            hops.append((rid, y))
            prev_id = rid
            y += RELAY_HOP
        col_entry[col] = hops[0]
        for i in range(col * rows_per_col, min((col + 1) * rows_per_col, n)):
            row = i - col * rows_per_col
            ry = row * 2 + ROW_DY
            nearest_rid, _ = min(hops, key=lambda hy: abs(hy[1] - ry))
            store = ConstantCombinator(id=f"{name}_store_{i}", tile_position=(origin_x + col * COL_SPACING, origin_y + ry))
            store.set_signal(index=0, name=out_signal, count=values[i])
            bp.entities.append(store)
            read = DeciderCombinator(
                id=f"{name}_read_{i}", tile_position=(origin_x + col * COL_SPACING + 2, origin_y + ry),
                conditions=[DeciderCombinator.Condition(first_signal=cond_signal, comparator="=", constant=i)],
                outputs=[DeciderCombinator.Output(signal=out_signal, copy_count_from_input=True)],
            )
            bp.entities.append(read)
            bp.add_circuit_connection(RED, f"{name}_store_{i}", f"{name}_read_{i}", side_2="input")
            bp.add_circuit_connection(GREEN, nearest_rid, f"{name}_read_{i}", side_1="output", side_2="input")

    for col in range(n_cols):
        hid = f"{name}_hrelay_{col}"
        bp.entities.append(ArithmeticCombinator(id=hid, position=(origin_x + col * COL_SPACING, origin_y - RELAY_HOP - 2),
                                                first_operand=cond_signal, operation="*", second_operand=1, output_signal=cond_signal))
        if col > 0:
            bp.add_circuit_connection(GREEN, f"{name}_hrelay_{col-1}", hid, side_1="output", side_2="input")
        bp.add_circuit_connection(GREEN, hid, col_entry[col][0], side_1="output", side_2="input")

    col_collectors = {}
    for col in range(n_cols):
        rows_here = min(rows_per_col, n - col * rows_per_col)
        max_y = (rows_here - 1) * 2
        n_hops = math.ceil(max_y / RELAY_HOP) + 1
        prev_id, y = None, max_y + RELAY_HOP
        hops = []
        for hop in range(n_hops):
            rid = f"{name}_crelay_{col}_{hop}"
            bp.entities.append(ArithmeticCombinator(id=rid, tile_position=(origin_x + col * COL_SPACING + 3, origin_y + y),
                                                    first_operand=out_signal, operation="*", second_operand=1, output_signal=out_signal))
            if prev_id is not None:
                bp.add_circuit_connection(RED, rid, prev_id, side_1="output", side_2="input")
            hops.append((rid, y))
            prev_id = rid
            y -= RELAY_HOP
        col_collectors[col] = hops[0][0]
        for i in range(col * rows_per_col, min((col + 1) * rows_per_col, n)):
            row = i - col * rows_per_col
            ry = row * 2 + ROW_DY
            nearest_rid, _ = min(hops, key=lambda hy: abs(hy[1] - ry))
            bp.add_circuit_connection(RED, f"{name}_read_{i}", nearest_rid, side_1="output", side_2="input")

    for col in range(1, n_cols):
        bp.add_circuit_connection(RED, col_collectors[col - 1], col_collectors[col], side_1="output", side_2="input")


ROM_X, ROM_Y = 0, 40
build_addressed_rom("t", VALUES, "signal-N", "signal-X", ROM_X, ROM_Y)

fn = f"stage2_rom_revive_isolated_test_{MODE}_blueprint.txt"
with open(fn, "w") as f:
    f.write(bp.to_string())

hop_ys = set()
for col in range(N_VALUES // ROWS_PER_COL):
    max_y = (ROWS_PER_COL - 1) * 2
    n_hops = math.ceil(max_y / RELAY_HOP) + 1
    for h in range(n_hops):
        hop_ys.add(-RELAY_HOP + h * RELAY_HOP)
        hop_ys.add(max_y + RELAY_HOP - h * RELAY_HOP)
coincide = sorted(r for r in range(ROWS_PER_COL) if (r * 2 + ROW_DY) in hop_ys)
n_dec = sum(1 for e in bp.entities if e.name == "decider-combinator")
print(f"MODE={MODE} entities={len(bp.entities)} deciders={n_dec} (expect {N_VALUES})")
print(f"hop y-offsets={sorted(hop_ys)}  rows coinciding with a hop y -> predicted revive loss: {coincide}")
print(f"Saved {fn}")
