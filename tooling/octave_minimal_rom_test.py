"""
Follow-up to octave_minimal_isolated_test.py (confirmed live: a single static
comparator + collector + rename chain gives a stable o_collect=1, no growth
- see Reshenie 27). That test never touched the ROM/address-sweep machinery
at all. This test changes EXACTLY ONE thing: value_bc's source is now a
tiny 2-word ROM (build_addressed_rom, the SAME already-topology-verified
helper used by stage2_octave_isolated_test.py - not reopening that question,
see Reshenie 27's "NOT to reopen" list) addressed by t_ctr/K, instead of a
ConstantCombinator that never changes. Everything downstream (relay chain,
single comparator, collector, o_collect rename) is otherwise identical in
shape to the already-proven-stable minimal test.

Goal: find out whether the systematic "o = 2^(address index) * true value"
bug (seen with 30 comparators + 6-word ROM in the full isolated test) is
already present with just ONE comparator and a 2-word ROM - i.e. whether
the bug needs "many comparators" or just needs "value_bc changing over time
via ROM addressing" at all, per Reshenie 27's open question / PROGRESS.md
item 11.

Both ROM words (3 and 5) are >=2 (the comparator's threshold), so the
comparator's constant-output condition (signal-I=1, not copy_count) means
the CORRECT o_collect is 1 at BOTH addresses regardless of which word is
active - any deviation from 1 at address 1 (e.g. o=2) is the same
"x2^address" signature already seen, now isolated to a single comparator.

Captures BOTH a gated snapshot per address (addr==i AND tmod==PULSE_TICK,
same anti-transient mid-window timing as Reshenie 26) AND is meant to be
paired with a live on_tick logger (registered after build, see the
companion _logger_cmd script) watching o_collect/value_bc/collect_0 raw
signal changes tick-by-tick, so a transient (not just a settled-wrong
snapshot) is visible too - the full test's own per-tick log showed
o_collect never settling within an address window (Reshenie 27), a gated
snapshot alone would not have shown that.
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

TEST_VALS = [3, 5]      # both >= THRESHOLD -> expected o_collect=1 at every address
THRESHOLD = 2
N_TEST = len(TEST_VALS)

K = 1800  # 30s/address at 60 UPS - "short K" per the session hand-off note;
# short enough for a quick automated round trip (no manual clipboard steps
# needed - AUTOMATION.md's import_stack/build_blueprint pipeline is used
# directly), long enough to comfortably register an on_tick logger and
# observe multiple ticks of settled behavior within each address window.
PULSE_TICK = K // 2  # mid-window capture, same reasoning as Reshenie 26:
# edges of the window are where transients live, not the middle.

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "octave minimal ROM-driven single-comparator test"

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
    """Verbatim copy of stage2_octave_isolated_test.py's helper (already
    confirmed topologically exact - 429/429 entities, 592 wires, Reshenie
    27 - not reopening that). Reused as-is at n=2 so the ROM addressing
    mechanism under test is IDENTICAL to the one in the full detector, not
    a reimplementation that could quietly differ."""
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


# ---- well-separated block origins (Reshenie 22's discipline: generous
# gaps, bridge() between them) ----
CTRL_X, CTRL_Y = 0, 0
VROM_X, VROM_Y = 0, 60
CMP_X, CMP_Y = 100, 0
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

# value_bc: rename ROM's collected signal-V into a clean, local, private
# signal-V - same role as the full detector's value_bc (Reshenie 27).
value_bc_pos = (CMP_X - 20 + 0.5, CMP_Y - 1.0)
value_bc = ArithmeticCombinator(id="value_bc", position=value_bc_pos, first_operand="signal-V", operation="+", second_operand=0, output_signal="signal-V")
bp.entities.append(value_bc)
bridge_to(vc_id, vc_pos, "value_bc", value_bc_pos, RED)

# short 3-hop relay chain - same broadcast-passthrough shape the ORIGINAL
# static minimal test used and already proved stable, kept here unchanged
# so the only thing that differs from that proven-good test is the ROM
# upstream of value_bc, nothing downstream of it.
relay_positions = [(CMP_X - 12, CMP_Y - 1), (CMP_X - 8, CMP_Y - 1), (CMP_X - 4, CMP_Y - 1)]
prev_id, prev_pos = "value_bc", value_bc_pos
for i, pos in enumerate(relay_positions):
    rid = f"relay_{i}"
    rpos = (pos[0] + 0.5, pos[1] + 1.0)
    e = ArithmeticCombinator(id=rid, position=rpos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(e)
    bp.add_circuit_connection(RED, prev_id, rid, side_1="output", side_2="input")
    prev_id, prev_pos = rid, rpos
bc_end, bc_end_pos = prev_id, prev_pos

cmp_pos = (CMP_X + 0.5, CMP_Y + 1.0)
cmp_e = DeciderCombinator(
    id="cmp_0", position=cmp_pos,
    conditions=[DeciderCombinator.Condition(first_signal="signal-V", comparator=">=", constant=THRESHOLD)],
    outputs=[DeciderCombinator.Output(signal="signal-I", copy_count_from_input=False, constant=1)],
)
bp.entities.append(cmp_e)
bp.add_circuit_connection(RED, bc_end, "cmp_0", side_1="output", side_2="input")

collect_pos = (CMP_X + 0.5, CMP_Y + 4.0)
collect_e = ArithmeticCombinator(id="collect_0", position=collect_pos, first_operand="signal-I", operation="*", second_operand=1, output_signal="signal-I")
bp.entities.append(collect_e)
bp.add_circuit_connection(RED, "cmp_0", "collect_0", side_1="output", side_2="input")

o_collect_pos = (CMP_X + 0.5, CMP_Y + 7.0)
o_collect = ArithmeticCombinator(id="o_collect", position=o_collect_pos, first_operand="signal-I", operation="+", second_operand=0, output_signal="signal-O")
bp.entities.append(o_collect)
bp.add_circuit_connection(RED, "collect_0", "o_collect", side_1="output", side_2="input")

# ---- per-address gated capture (addr==i AND tmod==PULSE_TICK), same shape
# as gate_j/acc_j in the full test - o_collect already has a real consumer
# here (the gates), so no dummy sink is needed (Reshenie 5/27's terminal-
# node lesson doesn't apply, unlike the earlier static test where it did).
SLOT_W2 = 10
o_spine_target = (ACC_X, ACC_Y - 3)
o_spine, o_spine_pos, _ = bridge("o_collect", o_collect_pos, o_spine_target, RED, hop=5)
# L-shaped route (Reshenie 8's fix pattern), not a direct diagonal: a
# straight line from ctrl_merge (3.5,4.0) to (150,-5) cuts through the CMP
# block's own territory (value_bc/relay_0-2/cmp_0/collect_0/o_collect all
# sit around x=80-100, y=-1..7) - found live as an OverlappingObjectsWarning
# at hop 11 landing at (80.24,-0.71), 0.39 tiles from value_bc. Going down
# to y=ACC_Y-5 FIRST (clear of the whole CMP block, 4+ tile margin) at
# ctrl_merge's own x, then across only once past it, avoids the block
# entirely instead of tuning hop size to dodge one coincidental crossing.
ctrl_spine_target = (ACC_X, ACC_Y - 5)
ctrl_wp0_id, ctrl_wp0_pos, _ = bridge("ctrl_merge", ctrl_merge_pos, (ctrl_merge_pos[0], ACC_Y - 5), GREEN, hop=7)
ctrl_spine, ctrl_spine_pos, _ = bridge(ctrl_wp0_id, ctrl_wp0_pos, ctrl_spine_target, GREEN, hop=7)

o_taps, ctrl_taps = [(o_spine, o_spine_pos)], [(ctrl_spine, ctrl_spine_pos)]
for i in range(1, N_TEST):
    tap_x = ACC_X + i * SLOT_W2
    o_spine, o_spine_pos, _ = bridge(o_spine, o_spine_pos, (tap_x, ACC_Y - 3), RED)
    o_taps.append((o_spine, o_spine_pos))
    ctrl_spine, ctrl_spine_pos, _ = bridge(ctrl_spine, ctrl_spine_pos, (tap_x, ACC_Y - 5), GREEN, hop=7)
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
        outputs=[DeciderCombinator.Output(signal="signal-O", copy_count_from_input=True)],
    )
    bp.entities.append(gate)
    bp.add_circuit_connection(RED, o_taps[i][0], f"gate_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, ctrl_taps[i][0], f"gate_{i}", side_1="output", side_2="input")

    acc_o = ArithmeticCombinator(id=f"acc_o_{i}", position=(gx + 2.5, gy + 1.0), first_operand="signal-A", operation="+", second_operand="signal-O", output_signal="signal-A")
    bp.entities.append(acc_o)
    bp.add_circuit_connection(RED, f"acc_o_{i}", f"acc_o_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"gate_{i}", f"acc_o_{i}", side_1="output", side_2="input")

# ---- power: generous lattice, same fast approach as Reshenie 15/27 ----
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
with open("octave_minimal_rom_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)

all_xs = [pos_of(e)[0] for e in bp.entities]
all_ys = [pos_of(e)[1] for e in bp.entities]
print(f"Full bbox: x=[{min(all_xs):.1f},{max(all_xs):.1f}] y=[{min(all_ys):.1f},{max(all_ys):.1f}]")
print(f"Entities: {len(bp.entities)}")
print(f"K={K}, PULSE_TICK={PULSE_TICK}, N_TEST={N_TEST}, full sweep = {N_TEST*K} ticks (~{N_TEST*K/60:.0f}s)")
print(f"TEST_VALS={TEST_VALS}, THRESHOLD={THRESHOLD} -> expected o_collect=1 at every address")
print(f"t_ctr local pos = {(CTRL_X+0.5, CTRL_Y+1.0)}")
print(f"o_collect local pos = {o_collect_pos}")
print(f"value_bc local pos = {value_bc_pos}")
print(f"collect_0 local pos = {collect_pos}")
print("Saved octave_minimal_rom_test_blueprint.txt")
