"""
Stage 2 capacity stress test: NOT a UPS measurement (Etap 0.5 already showed
UPS/tick isn't the binding constraint once Reshenie 1 accepts UPS down to
0.1). This measures the OTHER ceiling that matters for the real generative
model: how many addressed-ROM cells can actually be built/revived/wired up
correctly in practice, at what point does the entity/wire loss rate (already
known to be ~2-4% at the classifier's 29800-entity scale, per PROJECT.md
Reshenie 9) get worse, and where does the game/engine itself start to
struggle (import time, editor responsiveness, crashes).

Cell design simplified from proc_demo_export.py's proven pattern, based on
a cleaner idea already used (without noticing at the time) in
export_full.py's own syllable detectors: a decider's condition constant can
be baked into the blueprint at BUILD time (per-cell, distinct), so there is
no need for a per-cell "local address" SIGNAL at all - only the cell's
VALUE needs to be a signal. This removes the whole signal-N bookkeeping
and, not incidentally, removes one whole class of the RED/GREEN merge bug
found in Reshenie 14 (the per-cell data that must stay private is now just
ONE signal, not two).

  store_i = ConstantCombinator{signal-W: value_i}              (RED, private to read_i)
  read_i  = DeciderCombinator{condition: signal-A == i (constant, not
            a signal), output: signal-W (copy_count_from_input)}
  read_i's GREEN side carries the broadcast address (signal-A, same
  value reaching every cell - intentional, safe to merge with itself).
  RED (store_i - read_i) stays private per cell - never safe to merge
  (see Reshenie 14) since signal-W must not sum across cells.

TEST_ADDR is set to the LAST cell (N-1), not cell 0 - a stronger check that
the broadcast actually reaches all the way to the geometrically farthest
column, not just the nearest one.

Layout/relay/collector code below is adapted directly from export_full.py's
already-proven detector-layer + power-grid sections (same helper functions,
same discipline) rather than re-derived from scratch - see PROJECT.md
Reshenie 8/11 for why each piece of that pattern looks the way it does.
"""

import math
import sys

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200  # cell count - smoke test default
ROWS_PER_COL = 25
COL_SPACING = 4
RELAY_HOP = 8
RED = "red"
GREEN = "green"

TEST_ADDR = N - 1  # farthest cell from the broadcast source - strongest reach test

n_cols = math.ceil(N / ROWS_PER_COL)
_BUILD_TAG = "smoke test" if N < 5000 else "capacity probe"
_OUTPUT_FILE = f"rom_stress_{N}.txt"

bp = Blueprint()
bp.label = f"stage2 ROM capacity stress ({_BUILD_TAG}, N={N})"

# ---- N cells: store_i (RED, private) + read_i (condition == constant i,
# no per-cell signal needed for the address match itself - see docstring) ----
cell_col = {}  # global i -> (col, row)
for i in range(N):
    col, row = divmod(i, ROWS_PER_COL)
    cell_col[i] = (col, row)
    x = col * COL_SPACING
    y = row * 2
    store = ConstantCombinator(id=f"store_{i}", tile_position=(x, y))
    store.set_signal(index=0, name="signal-W", count=i)
    bp.entities.append(store)
    read = DeciderCombinator(
        id=f"read_{i}", tile_position=(x + 2, y),
        conditions=[DeciderCombinator.Condition(first_signal="signal-A", comparator="=", constant=i)],
        outputs=[DeciderCombinator.Output(signal="signal-W", copy_count_from_input=True)],
    )
    bp.entities.append(read)
    bp.add_circuit_connection(RED, f"store_{i}", f"read_{i}", side_2="input")

print(f"N={N}, columns={n_cols}, rows/col={ROWS_PER_COL}")

# ---- address broadcast source ----
addr_src = ConstantCombinator(id="addr_src", tile_position=(-4, 0))
addr_src.set_signal(index=0, name="signal-A", count=TEST_ADDR)
bp.entities.append(addr_src)

# ---- per-column GREEN vertical relay (broadcast down), tapped by every
# read_i in that column - same structure as export_full.py's colv_w_hop,
# just carrying the address broadcast DOWN instead of collecting values UP ----
col_entry = {}  # col -> id of the topmost relay point in that column (entry point for the horizontal spine)
for col in range(n_cols):
    rows_here = min(ROWS_PER_COL, N - col * ROWS_PER_COL)
    max_y = (rows_here - 1) * 2
    n_hops = math.ceil(max_y / RELAY_HOP) + 1
    prev_id, y = None, -RELAY_HOP  # spine sits above row 0 (y=0), first hop at y=-RELAY_HOP
    hop_positions = []
    for hop in range(n_hops):
        rid = f"vrelay_{col}_{hop}"
        e = ArithmeticCombinator(id=rid, tile_position=(col * COL_SPACING + 1, y), first_operand="signal-A", operation="*", second_operand=1, output_signal="signal-A")
        bp.entities.append(e)
        if prev_id is not None:
            bp.add_circuit_connection(GREEN, prev_id, rid, side_1="output", side_2="input")
        hop_positions.append((rid, y))
        prev_id = rid
        y += RELAY_HOP
    col_entry[col] = hop_positions[0][0]  # topmost (smallest y) hop feeds the horizontal spine
    for i in range(col * ROWS_PER_COL, min((col + 1) * ROWS_PER_COL, N)):
        _, row = cell_col[i]
        ry = row * 2
        nearest_rid, _ = min(hop_positions, key=lambda hy: abs(hy[1] - ry))
        bp.add_circuit_connection(GREEN, nearest_rid, f"read_{i}", side_1="output", side_2="input")

# ---- horizontal GREEN spine across all columns, fed by addr_src ----
prev_id = "addr_src"
spine_y = -RELAY_HOP - 2
for col in range(n_cols):
    hid = f"hrelay_{col}"
    e = ArithmeticCombinator(id=hid, tile_position=(col * COL_SPACING, spine_y), first_operand="signal-A", operation="*", second_operand=1, output_signal="signal-A")
    bp.entities.append(e)
    if prev_id == "addr_src":
        bp.add_circuit_connection(GREEN, prev_id, hid, side_2="input")
    else:
        bp.add_circuit_connection(GREEN, prev_id, hid, side_1="output", side_2="input")
    prev_id = hid
    bp.add_circuit_connection(GREEN, hid, col_entry[col], side_1="output", side_2="input")

print(f"Broadcast spine: {n_cols} horizontal relays + per-column vertical taps done")

# ---- RED output collection: every read_i's output feeds the nearest
# per-column vertical collector (separate RED network, output side only -
# never touches the RED input-side private links, different port) ----
col_collector_entry = {}
for col in range(n_cols):
    rows_here = min(ROWS_PER_COL, N - col * ROWS_PER_COL)
    max_y = (rows_here - 1) * 2
    n_hops = math.ceil(max_y / RELAY_HOP) + 1
    prev_id, y = None, max_y + RELAY_HOP
    hop_positions = []
    for hop in range(n_hops):
        rid = f"ccol_{col}_{hop}"
        e = ArithmeticCombinator(id=rid, tile_position=(col * COL_SPACING + 3, y), first_operand="signal-W", operation="*", second_operand=1, output_signal="signal-W")
        bp.entities.append(e)
        if prev_id is not None:
            bp.add_circuit_connection(RED, rid, prev_id, side_1="output", side_2="input")
        hop_positions.append((rid, y))
        prev_id = rid
        y -= RELAY_HOP
    col_collector_entry[col] = prev_id  # bottom-most hop (smallest y reached) feeds the horizontal collector
    for i in range(col * ROWS_PER_COL, min((col + 1) * ROWS_PER_COL, N)):
        _, row = cell_col[i]
        ry = row * 2
        nearest_rid, _ = min(hop_positions, key=lambda hy: abs(hy[1] - ry))
        bp.add_circuit_connection(RED, f"read_{i}", nearest_rid, side_1="output", side_2="input")

prev_id = col_collector_entry[0]
for col in range(1, n_cols):
    cur = col_collector_entry[col]
    bp.add_circuit_connection(RED, cur, prev_id, side_1="output", side_2="input")
    prev_id = cur

RESULT_ID = prev_id
print(f"Collector done, result at {RESULT_ID}")

# ---- power: export_full.py's gap-fill approach (Reshenie 11) is O(new
# sources x entities) per registration - fine for its irregular, clustered
# geometry where few extra sources were ever needed, but this script's
# layout is a long UNIFORM strip (thousands of columns), which needs many
# lattice substations just to span the width - registering each one against
# every entity (the export_full.py pattern) would be O(lattice_size x
# entities), quadratic again just with a smaller constant (measured: killed
# a real run at N=50000 after 22 CPU-minutes still not done, see PROJECT.md
# Reshenie 15). Fix: since the geometry IS uniform (unlike export_full.py's),
# skip iterative gap-fill entirely - place one regular lattice, then verify
# coverage with a SINGLE O(entities) bucketed nearest-lookup pass instead of
# re-scanning everything after every new source.
def pos_of(e):
    p = e.position
    return (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])


powered_types = {"arithmetic-combinator", "decider-combinator"}
entities_needing_power = [(e, pos_of(e)) for e in bp.entities if e.name in powered_types]

BUCKET = 2
occupied_bucket = {}
for e in bp.entities:
    px, py = pos_of(e)
    key = (int(px // BUCKET), int(py // BUCKET))
    occupied_bucket.setdefault(key, []).append((px, py))


def is_free(cx, cy, min_dist_x=1.05, min_dist_y=1.4):
    kx, ky = int(cx // BUCKET), int(cy // BUCKET)
    for bx in (kx - 1, kx, kx + 1):
        for by in (ky - 1, ky, ky + 1):
            for ox, oy in occupied_bucket.get((bx, by), []):
                if abs(ox - cx) < min_dist_x and abs(oy - cy) < min_dist_y:
                    return False
    return True


def mark_occupied(cx, cy):
    key = (int(cx // BUCKET), int(cy // BUCKET))
    occupied_bucket.setdefault(key, []).append((cx, cy))


def find_free_spot(cx, cy, max_radius=10, min_dist_x=1.05, min_dist_y=1.4):
    if is_free(cx, cy, min_dist_x, min_dist_y):
        return (cx, cy)
    for r in range(1, max_radius + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                cand = (cx + dx, cy + dy)
                if is_free(*cand, min_dist_x, min_dist_y):
                    return cand
    return None


# ---- bucketed power-source index: O(1) nearest-lookup instead of scanning
# the full power_net list (which is what made nearest_power/_register_power_
# source expensive at thousands of sources in the old approach) ----
POWER_BUCKET = 9  # ~ substation reach, so a 3x3 bucket neighborhood always covers anything within reach
power_bucket = {}
power_list = []  # (id, x, y, radius) - kept only for the EEI anchor at the end


def add_power_source(pid, x, y, radius):
    power_list.append((pid, x, y, radius))
    key = (int(x // POWER_BUCKET), int(y // POWER_BUCKET))
    power_bucket.setdefault(key, []).append((pid, x, y, radius))


def nearest_power_bucketed(x, y, search_radius=40):
    kx, ky = int(x // POWER_BUCKET), int(y // POWER_BUCKET)
    span = math.ceil(search_radius / POWER_BUCKET) + 1
    best, best_d = None, 1e18
    for bx in range(kx - span, kx + span + 1):
        for by in range(ky - span, ky + span + 1):
            for pid, px, py, pr in power_bucket.get((bx, by), ()):
                d = math.hypot(px - x, py - y)
                if d < best_d:
                    best_d, best = d, (pid, px, py, pr)
    return best


# regular lattice, spacing under substation reach*2 for overlap margin (same
# 12-tile spacing already proven at 5000+ combinator scale in
# stress_test_wired_export.py, Etap 0.5)
SUB_SPACING = 12
xs_all = [pos_of(e)[0] for e in bp.entities]
ys_all = [pos_of(e)[1] for e in bp.entities]
min_x, max_x = min(xs_all), max(xs_all)
min_y, max_y = min(ys_all), max(ys_all)
n_sub_cols = math.ceil((max_x - min_x) / SUB_SPACING) + 1
n_sub_rows = math.ceil((max_y - min_y) / SUB_SPACING) + 1

sub_lattice, sub_positions = {}, {}
for r in range(n_sub_rows):
    for c in range(n_sub_cols):
        sx, sy = min_x + c * SUB_SPACING, min_y + r * SUB_SPACING
        spot = find_free_spot(sx, sy)
        if spot is None:
            continue
        fx, fy = spot
        sub_id = f"sub_{r}_{c}"
        bp.entities.append(ElectricPole(name="substation", id=sub_id, position=(fx, fy), quality="legendary"))
        mark_occupied(fx, fy)
        add_power_source(sub_id, fx, fy, 9)
        sub_lattice[(r, c)] = sub_id
        sub_positions[(r, c)] = (fx, fy)

for (r, c), sub_id in sub_lattice.items():
    pos_a = sub_positions[(r, c)]
    for nr, nc in ((r, c + 1), (r + 1, c)):
        neighbor_id = sub_lattice.get((nr, nc))
        if neighbor_id is None:
            continue
        pos_b = sub_positions[(nr, nc)]
        dist = math.hypot(pos_b[0] - pos_a[0], pos_b[1] - pos_a[1])
        if dist <= 17:
            bp.add_power_connection(sub_id, neighbor_id)
        else:
            n_hops = math.ceil(dist / 8)
            prev_pid, prev_pos = sub_id, pos_a
            for h in range(1, n_hops):
                t = h / n_hops
                target = (pos_a[0] + (pos_b[0] - pos_a[0]) * t, pos_a[1] + (pos_b[1] - pos_a[1]) * t)
                spot = find_free_spot(*target, max_radius=4, min_dist_x=0.55, min_dist_y=0.85) or target
                rid = f"sub_link_relay_{r}_{c}_{h}"
                bp.entities.append(ElectricPole(name="medium-electric-pole", id=rid, position=spot, quality="legendary"))
                mark_occupied(*spot)
                bp.add_power_connection(prev_pid, rid)
                prev_pid, prev_pos = rid, spot
            bp.add_power_connection(prev_pid, neighbor_id)

# ---- single verification pass: for every powered entity, find its nearest
# source via the bucket (O(1) each) - if uncovered, drop ONE targeted pole
# right next to it (no rescan of everything else, no iterative worst-first
# search - each fix is local and independent since the layout is uniform) ----
gap_fill_count = 0
worst_slack = -1e9
for e, (ex, ey) in entities_needing_power:
    nearest = nearest_power_bucketed(ex, ey)
    slack = math.hypot(nearest[1] - ex, nearest[2] - ey) - nearest[3] if nearest else 1e9
    if slack > worst_slack:
        worst_slack = slack
    if slack > 0:
        spot = find_free_spot(ex, ey, max_radius=3, min_dist_x=0.55, min_dist_y=0.85) or (ex, ey)
        fx, fy = spot
        gap_fill_count += 1
        pole_id = f"pole_gap_{gap_fill_count}"
        bp.entities.append(ElectricPole(name="medium-electric-pole", id=pole_id, position=(fx, fy), quality="legendary"))
        mark_occupied(fx, fy)
        link = nearest_power_bucketed(fx, fy, search_radius=9)
        if link is not None and math.hypot(link[1] - fx, link[2] - fy) <= 9:
            bp.add_power_connection(pole_id, link[0])
        add_power_source(pole_id, fx, fy, 3.5)

print(f"Gap-fill: {gap_fill_count} poles, worst slack before gap-fill: {worst_slack:.2f} tiles (<=0 means the lattice alone already covered everything)")

anchor_x, anchor_y = next(iter(sub_positions.values()))
eei_spot = find_free_spot(anchor_x - 3, anchor_y) or (anchor_x - 3, anchor_y)
eei = ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=eei_spot, buffer_size=10**9)
bp.entities.append(eei)

print(f"Power: {len(sub_lattice)} lattice substations + {gap_fill_count} gap poles + 1 EEI")
print(f"Total entities: {len(bp.entities)}")
print(f"Expected: read_{TEST_ADDR} outputs signal-W={TEST_ADDR}, collected at {RESULT_ID}")

blueprint_string = bp.to_string()
with open(_OUTPUT_FILE, "w") as f:
    f.write(blueprint_string)
print(f"Saved {_OUTPUT_FILE}")
