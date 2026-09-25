"""
Third bisection step, following Reshenie 30's finding that N_CMP=3 comparators
sharing a broadcast spine + cascading collector (the ONE piece the N=1 test
of Reshenie 29 skipped) is STILL clean - o_collect came out exactly right at
both addresses (1 and 2), no growth. That rules out "just needs multiple
comparators" as the cause.

This test adds the ONE remaining piece of stage2_octave_isolated_test.py's
topology that NEITHER Reshenie 29 nor Reshenie 30's test has ever exercised:
a DOWNSTREAM ROM READ addressed by o_collect's own output (signal-O) - the
oct_lower lookup (build_addressed_rom("olrom", OCT_LOWER, "signal-O", ...) in
the full detector). Worth testing specifically because Reshenie 27's own
per-tick log described o_collect as never settling within an address window,
sometimes bleeding into the NEXT address's window - continuous drift/growth,
not a bounded few-tick cascade delay. A downstream consumer that reads
o_collect and (if some connection direction bug exists - this project has
found several "missing side_1=output" bugs in exactly this file, Reshenie 27
point 4) accidentally feeds something back onto o_collect's own network would
explain sustained growth in a way "cascade settle time" cannot.

Small oct_lower ROM sized to N_CMP+1 words (octave range 0..N_CMP possible
with 3 comparators): OCT_LOWER_SMALL = [2**o for o in range(N_CMP+1)] =
[1,2,4,8], addressed by signal-O exactly like the real detector.

Everything upstream of o_collect (control block, value ROM, comparators,
collector cascade) is byte-for-byte identical to octave_multi_rom_test.py -
not reopening that, Reshenie 30 already confirmed it clean in isolation.

Expected (same TEST_VALS=[3,5], THRESHOLDS=[2,4,8] as Reshenie 30):
  address 0: value=3 -> o=1 -> L=OCT_LOWER_SMALL[1]=2
  address 1: value=5 -> o=2 -> L=OCT_LOWER_SMALL[2]=4
If o_collect itself gets corrupted by adding this downstream reader, o at
address 1 would show the same compounding signature already seen in the full
detector (Reshenie 27). If o stays correct but L is wrong, the bug is in the
ROM-read-by-signal-O mechanism itself, not in o_collect.
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

TEST_VALS = [3, 5]
N_TEST = len(TEST_VALS)

N_CMP = 3
THRESHOLDS = [2, 4, 8]
EXPECTED_O = []
for v in TEST_VALS:
    EXPECTED_O.append(sum(1 for t in THRESHOLDS if v >= t))

OCT_LOWER_SMALL = [2 ** o for o in range(N_CMP + 1)]  # [1,2,4,8]
EXPECTED_L = [OCT_LOWER_SMALL[o] for o in EXPECTED_O]

K = 1800
PULSE_TICK = K // 2

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "octave multi-comparator + downstream oct_lower ROM readback test"

RELAY_HOP = 8
COL_SPACING = 4
_bridge_ctr = 0


def bridge(from_id, from_pos, to_pos, color, hop=RELAY_HOP):
    global _bridge_ctr
    fx, fy = from_pos
    tx, ty = to_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist < 1e-9:
        return from_id, from_pos, 0
    n_hops = max(1, math.ceil(dist / hop))
    prev_id, prev_pos = from_id, from_pos
    for h in range(1, n_hops + 1):
        t = h / n_hops
        pos = (fx + (tx - fx) * t, fy + (ty - fy) * t)
        _bridge_ctr += 1
        bid = f"gbridge_{_bridge_ctr}"
        e = ArithmeticCombinator(id=bid, position=pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
        bp.entities.append(e)
        bp.add_circuit_connection(color, prev_id, bid, side_1="output", side_2="input")
        prev_id, prev_pos = bid, pos
    return prev_id, prev_pos, n_hops


def bridge_to(from_id, from_pos, target_id, target_pos, color, standoff=3, hop=RELAY_HOP):
    prev_id, prev_pos = from_id, from_pos
    tx, ty = target_pos
    fx, fy = prev_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist <= standoff + 1.5:
        bp.add_circuit_connection(color, prev_id, target_id, side_1="output", side_2="input")
        return
    t = (dist - standoff) / dist
    stop_pos = (fx + (tx - fx) * t, fy + (ty - fy) * t)
    last_id, _, _ = bridge(prev_id, prev_pos, stop_pos, color, hop=hop)
    bp.add_circuit_connection(color, last_id, target_id, side_1="output", side_2="input")


def build_addressed_rom(name, values, cond_signal, out_signal, origin_x, origin_y, rows_per_col=4):
    """Verbatim copy, not reopening (429/429 topologically exact, Reshenie 27)."""
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
            ry = row * 2
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

    spine_prev, spine_pos = None, None
    for col in range(n_cols):
        hid = f"{name}_hrelay_{col}"
        pos = (origin_x + col * COL_SPACING, origin_y - RELAY_HOP - 2)
        e = ArithmeticCombinator(id=hid, position=pos, first_operand=cond_signal, operation="*", second_operand=1, output_signal=cond_signal)
        bp.entities.append(e)
        if spine_prev is not None:
            bp.add_circuit_connection(GREEN, spine_prev, hid, side_1="output", side_2="input")
        spine_prev, spine_pos = hid, pos
        entry_id, entry_dy = col_entry[col]
        bp.add_circuit_connection(GREEN, hid, entry_id, side_1="output", side_2="input")
    broadcast_entry_id, broadcast_entry_pos = f"{name}_hrelay_0", (origin_x, origin_y - RELAY_HOP - 2)

    col_collectors = {}
    for col in range(n_cols):
        rows_here = min(rows_per_col, n - col * rows_per_col)
        max_y = (rows_here - 1) * 2
        n_hops = math.ceil(max_y / RELAY_HOP) + 1
        prev_id, y = None, max_y + RELAY_HOP
        hops = []
        for hop in range(n_hops):
            rid = f"{name}_crelay_{col}_{hop}"
            e = ArithmeticCombinator(id=rid, tile_position=(origin_x + col * COL_SPACING + 3, origin_y + y),
                                      first_operand=out_signal, operation="*", second_operand=1, output_signal=out_signal)
            bp.entities.append(e)
            if prev_id is not None:
                bp.add_circuit_connection(RED, rid, prev_id, side_1="output", side_2="input")
            hops.append((rid, y))
            prev_id = rid
            y -= RELAY_HOP
        col_collectors[col] = (prev_id, (origin_x + col * COL_SPACING + 3, origin_y + hops[-1][1]))
        for i in range(col * rows_per_col, min((col + 1) * rows_per_col, n)):
            row = i - col * rows_per_col
            ry = row * 2
            nearest_rid, _ = min(hops, key=lambda hy: abs(hy[1] - ry))
            bp.add_circuit_connection(RED, f"{name}_read_{i}", nearest_rid, side_1="output", side_2="input")

    prev, prev_pos = col_collectors[0]
    for col in range(1, n_cols):
        cur, cur_pos = col_collectors[col]
        bp.add_circuit_connection(RED, prev, cur, side_1="output", side_2="input")
        prev, prev_pos = cur, cur_pos
    return (broadcast_entry_id, broadcast_entry_pos), (prev, prev_pos)


# ---- well-separated block origins ----
CTRL_X, CTRL_Y = 0, 0
VROM_X, VROM_Y = 0, 60
CMP_X, CMP_Y = 100, 0
OLROM_X, OLROM_Y = 60, 30
ACC_X, ACC_Y = 150, 0

t_ctr = ArithmeticCombinator(id="t_ctr", position=(CTRL_X + 0.5, CTRL_Y + 1.0), first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T")
bp.entities.append(t_ctr)
bp.add_circuit_connection(RED, "t_ctr", "t_ctr", side_1="output", side_2="input")

addr = ArithmeticCombinator(id="addr", position=(CTRL_X + 0.5, CTRL_Y + 4.0), first_operand="signal-T", operation="/", second_operand=K, output_signal="signal-D")
bp.entities.append(addr)
bp.add_circuit_connection(RED, "t_ctr", "addr", side_1="output", side_2="input")

tmod = ArithmeticCombinator(id="tmod", position=(CTRL_X + 3.5, CTRL_Y + 1.0), first_operand="signal-T", operation="%", second_operand=K, output_signal="signal-M")
bp.entities.append(tmod)
bp.add_circuit_connection(RED, "t_ctr", "tmod", side_1="output", side_2="input")

ctrl_merge_pos = (CTRL_X + 3.5, CTRL_Y + 4.0)
ctrl_merge = ArithmeticCombinator(id="ctrl_merge", position=ctrl_merge_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(ctrl_merge)
bp.add_circuit_connection(GREEN, "addr", "ctrl_merge", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "tmod", "ctrl_merge", side_1="output", side_2="input")

# ---- value ROM: 2 words, addressed directly by addr (signal-D) ----
v_entry, v_collect_info = build_addressed_rom("vrom", TEST_VALS, "signal-D", "signal-V", VROM_X, VROM_Y, rows_per_col=2)
addr_pos = (CTRL_X + 0.5, CTRL_Y + 4.0)
bridge_to("addr", addr_pos, v_entry[0], v_entry[1], GREEN)
vc_id, vc_pos = v_collect_info

value_bc_pos = (CMP_X - 20 + 0.5, CMP_Y - 1.0)
value_bc = ArithmeticCombinator(id="value_bc", position=value_bc_pos, first_operand="signal-V", operation="+", second_operand=0, output_signal="signal-V")
bp.entities.append(value_bc)
bridge_to(vc_id, vc_pos, "value_bc", value_bc_pos, RED)

# ---- N_CMP parallel threshold comparators sharing ONE broadcast spine +
# cascading collector - identical to octave_multi_rom_test.py, confirmed
# clean in isolation by Reshenie 30, not reopened here. ----
SLOT_W = 3
SPINE_Y = CMP_Y - 3
bc_spine_target = (CMP_X, SPINE_Y)
bc_spine, bc_spine_pos, _ = bridge("value_bc", value_bc_pos, bc_spine_target, RED)

bc_taps = [(bc_spine, bc_spine_pos)]
for k in range(1, N_CMP):
    tap_x = CMP_X + k * SLOT_W
    bc_spine, bc_spine_pos, _ = bridge(bc_spine, bc_spine_pos, (tap_x, SPINE_Y), RED)
    bc_taps.append((bc_spine, bc_spine_pos))

for k in range(N_CMP):
    cx = CMP_X + k * SLOT_W
    cy = CMP_Y
    cmp_e = DeciderCombinator(
        id=f"cmp_{k}", position=(cx + 0.5, cy + 1.0),
        conditions=[DeciderCombinator.Condition(first_signal="signal-V", comparator=">=", constant=THRESHOLDS[k])],
        outputs=[DeciderCombinator.Output(signal="signal-I", copy_count_from_input=False, constant=1)],
    )
    bp.entities.append(cmp_e)
    bp.add_circuit_connection(RED, bc_taps[k][0], f"cmp_{k}", side_1="output", side_2="input")

collect_ids = {}
for k in range(N_CMP - 1, -1, -1):
    cx = CMP_X + k * SLOT_W
    cy = CMP_Y
    rid = f"collect_{k}"
    e = ArithmeticCombinator(id=rid, position=(cx + 0.5, cy + 3.0), first_operand="signal-I", operation="*", second_operand=1, output_signal="signal-I")
    bp.entities.append(e)
    collect_ids[k] = rid
    bp.add_circuit_connection(RED, f"cmp_{k}", rid, side_1="output", side_2="input")
    if k < N_CMP - 1:
        bp.add_circuit_connection(GREEN, collect_ids[k + 1], rid, side_1="output", side_2="input")

o_collect_pos = (CMP_X - 15 + 0.5, CMP_Y + 3.0)
o_collect = ArithmeticCombinator(id="o_collect", position=o_collect_pos, first_operand="signal-I", operation="+", second_operand=0, output_signal="signal-O")
bp.entities.append(o_collect)
bridge_to("collect_0", (CMP_X + 0.5, CMP_Y + 3.0), "o_collect", o_collect_pos, RED, standoff=3, hop=6)

# ---- NEW: downstream oct_lower ROM, addressed by o_collect's own signal-O -
# the ONE piece of the full detector's topology neither Reshenie 29 nor 30
# has tested. bridge_to reads FROM o_collect's OUTPUT only (side_1="output"),
# same discipline as every other broadcast source in this project - if this
# reproduces the bug, the direction of this specific connection is the first
# thing to re-check for a missing/wrong side_1 (Reshenie 27 point 1's exact
# bug class). ----
ol_entry, ol_collect_info = build_addressed_rom("olrom", OCT_LOWER_SMALL, "signal-O", "signal-L", OLROM_X, OLROM_Y, rows_per_col=2)
# L-shaped route (Reshenie 8/28's fix pattern), not a direct diagonal: a
# straight bridge_to from o_collect (85.5,3.0) to the ROM's entry (~60,20)
# cut through the ROM's own internal layout at both ends (caught live as
# two OverlappingObjectsWarnings). Descend at o_collect's own x first
# (clear of everything below it), cross at a safe y well above the ROM's
# broadcast row, then bridge_to the actual entry.
ol_wp0_id, ol_wp0_pos, _ = bridge("o_collect", o_collect_pos, (o_collect_pos[0], OLROM_Y - 15), GREEN, hop=6)
ol_wp1_id, ol_wp1_pos, _ = bridge(ol_wp0_id, ol_wp0_pos, (OLROM_X, OLROM_Y - 15), GREEN, hop=6)
bridge_to(ol_wp1_id, ol_wp1_pos, ol_entry[0], ol_entry[1], GREEN, hop=6)
olc_id, olc_pos = ol_collect_info

ol_local_pos = (CMP_X - 30 + 0.5, CMP_Y + 3.0)
ol_local = ArithmeticCombinator(id="ol_local", position=ol_local_pos, first_operand="signal-L", operation="+", second_operand=0, output_signal="signal-L")
bp.entities.append(ol_local)
bridge_to(olc_id, olc_pos, "ol_local", ol_local_pos, RED, hop=6)

# ---- per-address gated capture (addr==i AND tmod==PULSE_TICK), now
# capturing signal-O AND signal-L together (multi-output decider, same
# pattern as gate_j in stage2_octave_isolated_test.py capturing O+S).
#
# Three independent lanes (o/l/ctrl), each confined to its own strictly
# axis-aligned "L": descend at the source's own x, cross at a dedicated row,
# then rise (straight, same x) at a dedicated column - never a diagonal.
# Two earlier drafts used a final diagonal (or let approach columns
# converge) and both produced live OverlappingObjectsWarnings where two
# lanes' paths crossed near their common target. This layout is safe BY
# CONSTRUCTION: each lane's crossing row is strictly below (more negative
# than) every other lane's vertical-rise range, so no two lanes' entities
# can ever share a Y even where their X ranges overlap - verified by hand,
# not just tuned to dodge one coincidental hop (Reshenie 8's lesson, applied
# more rigorously here after two rounds of partial fixes).
SLOT_W2 = 10
O_ROW, L_ROW, CTRL_ROW = -20, -26, -32
O_COL, L_COL, CTRL_COL = 144, 147, 150

o_wp0_id, o_wp0_pos, _ = bridge("o_collect", o_collect_pos, (o_collect_pos[0], O_ROW), RED, hop=5)
o_wp1_id, o_wp1_pos, _ = bridge(o_wp0_id, o_wp0_pos, (O_COL, O_ROW), RED, hop=5)
o_spine_target = (O_COL, ACC_Y - 3)
o_spine, o_spine_pos, _ = bridge(o_wp1_id, o_wp1_pos, o_spine_target, RED, hop=5)

l_wp0_id, l_wp0_pos, _ = bridge("ol_local", ol_local_pos, (ol_local_pos[0], L_ROW), RED, hop=5)
l_wp1_id, l_wp1_pos, _ = bridge(l_wp0_id, l_wp0_pos, (L_COL, L_ROW), RED, hop=5)
l_spine_target = (L_COL, ACC_Y - 5)
l_spine, l_spine_pos, _ = bridge(l_wp1_id, l_wp1_pos, l_spine_target, RED, hop=5)

ctrl_wp0_id, ctrl_wp0_pos, _ = bridge("ctrl_merge", ctrl_merge_pos, (ctrl_merge_pos[0], CTRL_ROW), GREEN, hop=7)
ctrl_wp1_id, ctrl_wp1_pos, _ = bridge(ctrl_wp0_id, ctrl_wp0_pos, (CTRL_COL, CTRL_ROW), GREEN, hop=7)
ctrl_spine_target = (CTRL_COL, ACC_Y - 7)
ctrl_spine, ctrl_spine_pos, _ = bridge(ctrl_wp1_id, ctrl_wp1_pos, ctrl_spine_target, GREEN, hop=7)

o_taps, l_taps, ctrl_taps = [(o_spine, o_spine_pos)], [(l_spine, l_spine_pos)], [(ctrl_spine, ctrl_spine_pos)]
for i in range(1, N_TEST):
    tap_x = ACC_X + i * SLOT_W2
    o_spine, o_spine_pos, _ = bridge(o_spine, o_spine_pos, (tap_x, ACC_Y - 3), RED)
    o_taps.append((o_spine, o_spine_pos))
    l_spine, l_spine_pos, _ = bridge(l_spine, l_spine_pos, (tap_x, ACC_Y - 5), RED)
    l_taps.append((l_spine, l_spine_pos))
    ctrl_spine, ctrl_spine_pos, _ = bridge(ctrl_spine, ctrl_spine_pos, (tap_x, ACC_Y - 7), GREEN, hop=7)
    ctrl_taps.append((ctrl_spine, ctrl_spine_pos))

for i in range(N_TEST):
    gx = ACC_X + i * SLOT_W2
    gy = ACC_Y
    gate_pos = (gx + 0.5, gy + 1.0)
    gate = DeciderCombinator(
        id=f"gate_{i}", position=gate_pos,
        conditions=[
            DeciderCombinator.Condition(first_signal="signal-D", comparator="=", constant=i, compare_type="and"),
            DeciderCombinator.Condition(first_signal="signal-M", comparator="=", constant=PULSE_TICK, compare_type="and"),
        ],
        outputs=[
            DeciderCombinator.Output(signal="signal-O", copy_count_from_input=True),
            DeciderCombinator.Output(signal="signal-L", copy_count_from_input=True),
        ],
    )
    bp.entities.append(gate)
    bp.add_circuit_connection(RED, o_taps[i][0], f"gate_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, l_taps[i][0], f"gate_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, ctrl_taps[i][0], f"gate_{i}", side_1="output", side_2="input")

    acc_o = ArithmeticCombinator(id=f"acc_o_{i}", position=(gx + 2.5, gy + 1.0), first_operand="signal-A", operation="+", second_operand="signal-O", output_signal="signal-A")
    bp.entities.append(acc_o)
    bp.add_circuit_connection(RED, f"acc_o_{i}", f"acc_o_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"gate_{i}", f"acc_o_{i}", side_1="output", side_2="input")

    acc_l = ArithmeticCombinator(id=f"acc_l_{i}", position=(gx + 4.5, gy + 1.0), first_operand="signal-B", operation="+", second_operand="signal-L", output_signal="signal-B")
    bp.entities.append(acc_l)
    bp.add_circuit_connection(RED, f"acc_l_{i}", f"acc_l_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"gate_{i}", f"acc_l_{i}", side_1="output", side_2="input")

# ---- power: generous lattice, same fast approach as prior sessions ----
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


POWER_BUCKET = 9
power_bucket = {}


def add_power_source(pid, x, y, radius):
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


_DEMAND_BUCKET = 8
_demand_bucket = {}
for _e, (_ex, _ey) in entities_needing_power:
    _key = (int(_ex // _DEMAND_BUCKET), int(_ey // _DEMAND_BUCKET))
    _demand_bucket.setdefault(_key, []).append((_ex, _ey))


def near_power_demand(x, y, radius=20):
    kx, ky = int(x // _DEMAND_BUCKET), int(y // _DEMAND_BUCKET)
    span = math.ceil(radius / _DEMAND_BUCKET) + 1
    for bx in range(kx - span, kx + span + 1):
        for by in range(ky - span, ky + span + 1):
            for ex, ey in _demand_bucket.get((bx, by), ()):
                if math.hypot(ex - x, ey - y) <= radius:
                    return True
    return False


SUB_SPACING = 12
xs_all = [pos_of(e)[0] for e in bp.entities]
ys_all = [pos_of(e)[1] for e in bp.entities]
min_x, max_x = min(xs_all), max(xs_all)
min_y, max_y = min(ys_all), max(ys_all)
n_sub_cols = math.ceil((max_x - min_x) / SUB_SPACING) + 1
n_sub_rows = math.ceil((max_y - min_y) / SUB_SPACING) + 1

sub_lattice, sub_positions = {}, {}
empty_skipped = 0
for r in range(n_sub_rows):
    for c in range(n_sub_cols):
        sx, sy = min_x + c * SUB_SPACING, min_y + r * SUB_SPACING
        if not near_power_demand(sx, sy, radius=20):
            empty_skipped += 1
            continue
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

anchor_x, anchor_y = next(iter(sub_positions.values()))
eei_spot = find_free_spot(anchor_x - 3, anchor_y) or (anchor_x - 3, anchor_y)
bp.entities.append(ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=eei_spot, buffer_size=10**9))

print(f"Power: {len(sub_lattice)} lattice substations ({empty_skipped} empty-territory points skipped) + {gap_fill_count} gap poles, worst slack before gap-fill: {worst_slack:.2f}")

blueprint_string = bp.to_string()
with open("octave_multi_rom_downstream_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)

all_xs = [pos_of(e)[0] for e in bp.entities]
all_ys = [pos_of(e)[1] for e in bp.entities]
print(f"Full bbox: x=[{min(all_xs):.1f},{max(all_xs):.1f}] y=[{min(all_ys):.1f},{max(all_ys):.1f}]")
print(f"Entities: {len(bp.entities)}")
print(f"K={K}, PULSE_TICK={PULSE_TICK}, N_TEST={N_TEST}, N_CMP={N_CMP}, full sweep = {N_TEST*K} ticks (~{N_TEST*K/60:.0f}s)")
print(f"TEST_VALS={TEST_VALS}, THRESHOLDS={THRESHOLDS} -> EXPECTED_O={EXPECTED_O}")
print(f"OCT_LOWER_SMALL={OCT_LOWER_SMALL} -> EXPECTED_L={EXPECTED_L}")
print(f"t_ctr local pos = {(CTRL_X+0.5, CTRL_Y+1.0)}")
print(f"o_collect local pos = {o_collect_pos}")
print(f"ol_local local pos = {ol_local_pos}")
print(f"value_bc local pos = {value_bc_pos}")
print(f"collect_0 local pos = {(CMP_X + 0.5, CMP_Y + 3.0)}")
print("Saved octave_multi_rom_downstream_test_blueprint.txt")
