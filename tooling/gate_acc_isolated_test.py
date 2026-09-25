"""
Isolates the gate/accumulator capture mechanism (gate_i -> acc_o_i/acc_s_i,
self-looping, multi-output decider) from EVERYTHING upstream of it - no ROM,
no comparators, no collector cascade. Motivated by a live finding on the
original stage2_octave_isolated_test.py detector (13.08.2026): o_collect's
own raw computed value, read via a SINGLE wire color, is provably correct
(8 for a value=256 test case - exact match to expected math). But the
GATED capture (acc_o_1, freshly recreated with a clean never-fired self-loop,
single RED-only read - immune to the separately-confirmed two-color
get_signals artifact) still showed exactly 2x the true value (14 instead of
7) after exactly one firing. That rules out both prior suspects (comparator
count, downstream ROM, and the two-color read artifact) and points squarely
at the gate->accumulator relay/self-loop mechanism itself.

This test feeds two CONSTANT, always-true values (O=7, S=31 - same numbers
as the original detector's address-1 test case, so a match/mismatch is
directly comparable) into a single gate+accumulator pair, structured
identically to gate_i/acc_o_i/acc_s_i in stage2_octave_isolated_test.py:
  - gate's condition: tmod == PULSE_TICK (single condition, no address
    check needed since there's only one test case here)
  - gate's outputs: signal-O and signal-S, both copy_count_from_input=True
  - gate's OUTPUT port feeds BOTH acc_o.input and acc_s.input via the SAME
    RED color (the exact shared-network shape suspected as the culprit)
  - acc_o/acc_s: self-looping accumulators (signal-A/signal-B), reading
    signal-O/signal-S from the shared gate-fed network

If acc_o ends up holding 14 (not 7) after one clean firing, the bug is
confirmed to live in this exact minimal shape, independent of everything
this project has built for the octave detector - meaning it likely also
lurks in the ALREADY-CLOSED matmul block's acc_j (Reshenie 26, which used
the identical pattern) and needs a project-wide fix, not just an octave
detector patch.
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

TRUE_O = 7
TRUE_S = 31

K = 1800
PULSE_TICK = K // 2

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "gate/accumulator isolated test - static O/S input"

RELAY_HOP = 8
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
        # ConstantCombinator has a single port - side_1="output" is invalid
        # for it (Reshenie 27's lesson), only applies on the first hop.
        single_port = h == 1 and any(x.id == prev_id and x.name == "constant-combinator" for x in bp.entities)
        if single_port:
            bp.add_circuit_connection(color, prev_id, bid, side_2="input")
        else:
            bp.add_circuit_connection(color, prev_id, bid, side_1="output", side_2="input")
        prev_id, prev_pos = bid, pos
    return prev_id, prev_pos, n_hops


CTRL_X, CTRL_Y = 0, 0
GATE_X, GATE_Y = 30, 0

t_ctr = ArithmeticCombinator(id="t_ctr", position=(CTRL_X + 0.5, CTRL_Y + 1.0), first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T")
bp.entities.append(t_ctr)
bp.add_circuit_connection(RED, "t_ctr", "t_ctr", side_1="output", side_2="input")

tmod = ArithmeticCombinator(id="tmod", position=(CTRL_X + 3.5, CTRL_Y + 1.0), first_operand="signal-T", operation="%", second_operand=K, output_signal="signal-M")
bp.entities.append(tmod)
bp.add_circuit_connection(RED, "t_ctr", "tmod", side_1="output", side_2="input")

# trivial address channel (always 0, matching gate_i's "addr==i" half of its
# AND condition in the original detector) - the ONLY structural difference
# from this file's first version, isolating whether the COMPOUND condition
# itself (compare_type="and", two conditions) is what causes doubling, since
# the single-condition version just tested came back clean (+7/firing, no
# doubling at all).
addr = ArithmeticCombinator(id="addr", position=(CTRL_X + 0.5, CTRL_Y + 4.0), first_operand="signal-T", operation="/", second_operand=K * 1000000, output_signal="signal-D")
bp.entities.append(addr)
bp.add_circuit_connection(RED, "t_ctr", "addr", side_1="output", side_2="input")

const_os = ConstantCombinator(id="const_os", tile_position=(CTRL_X, CTRL_Y + 7))
const_os.set_signal(index=0, name="signal-O", count=TRUE_O)
const_os.set_signal(index=1, name="signal-S", count=TRUE_S)
bp.entities.append(const_os)

# ctrl_merge: combine addr(signal-D) + tmod(signal-M) onto one GREEN network,
# same shape as the original detector's ctrl_merge - not tmod alone.
ctrl_merge_pos = (CTRL_X + 3.5, CTRL_Y + 4.0)
ctrl_merge = ArithmeticCombinator(id="ctrl_merge", position=ctrl_merge_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(ctrl_merge)
bp.add_circuit_connection(GREEN, "addr", "ctrl_merge", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "tmod", "ctrl_merge", side_1="output", side_2="input")

gate_pos = (GATE_X + 0.5, GATE_Y + 1.0)
mspine_id, mspine_pos, _ = bridge("ctrl_merge", ctrl_merge_pos, (GATE_X, GATE_Y - 3), GREEN, hop=6)

const_pos = (CTRL_X + 0.5, CTRL_Y + 7.0)
ospine_id, ospine_pos, _ = bridge("const_os", const_pos, (GATE_X, GATE_Y - 5), RED, hop=6)

gate = DeciderCombinator(
    id="gate_0", position=gate_pos,
    conditions=[
        DeciderCombinator.Condition(first_signal="signal-D", comparator="=", constant=0, compare_type="and"),
        DeciderCombinator.Condition(first_signal="signal-M", comparator="=", constant=PULSE_TICK, compare_type="and"),
    ],
    outputs=[
        DeciderCombinator.Output(signal="signal-O", copy_count_from_input=True),
        DeciderCombinator.Output(signal="signal-S", copy_count_from_input=True),
    ],
)
bp.entities.append(gate)
bp.add_circuit_connection(GREEN, mspine_id, "gate_0", side_1="output", side_2="input")
bp.add_circuit_connection(RED, ospine_id, "gate_0", side_1="output", side_2="input")

acc_o = ArithmeticCombinator(id="acc_o_0", position=(GATE_X + 2.5, GATE_Y + 1.0), first_operand="signal-A", operation="+", second_operand="signal-O", output_signal="signal-A")
bp.entities.append(acc_o)
bp.add_circuit_connection(RED, "acc_o_0", "acc_o_0", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "gate_0", "acc_o_0", side_1="output", side_2="input")

acc_s = ArithmeticCombinator(id="acc_s_0", position=(GATE_X + 4.5, GATE_Y + 1.0), first_operand="signal-B", operation="+", second_operand="signal-S", output_signal="signal-B")
bp.entities.append(acc_s)
bp.add_circuit_connection(RED, "acc_s_0", "acc_s_0", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "gate_0", "acc_s_0", side_1="output", side_2="input")

# ---- power: generous lattice, same approach as prior sessions ----
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


SUB_SPACING = 12
xs_all = [pos_of(e)[0] for e in bp.entities]
ys_all = [pos_of(e)[1] for e in bp.entities]
min_x, max_x = min(xs_all), max(xs_all)
min_y, max_y = min(ys_all), max(ys_all)
n_sub_cols = max(1, math.ceil((max_x - min_x) / SUB_SPACING) + 1)
n_sub_rows = max(1, math.ceil((max_y - min_y) / SUB_SPACING) + 1)

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

print(f"Power: {len(sub_lattice)} lattice substations + {gap_fill_count} gap poles, worst slack: {worst_slack:.2f}")

blueprint_string = bp.to_string()
with open("gate_acc_isolated_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)

all_xs = [pos_of(e)[0] for e in bp.entities]
all_ys = [pos_of(e)[1] for e in bp.entities]
print(f"Full bbox: x=[{min(all_xs):.1f},{max(all_xs):.1f}] y=[{min(all_ys):.1f},{max(all_ys):.1f}]")
print(f"Entities: {len(bp.entities)}")
print(f"K={K}, PULSE_TICK={PULSE_TICK}")
print(f"TRUE_O={TRUE_O}, TRUE_S={TRUE_S} -> expected acc_o=A={TRUE_O}, acc_s=B={TRUE_S} after one firing")
print(f"t_ctr local pos = {(CTRL_X+0.5, CTRL_Y+1.0)}")
print(f"tmod local pos = {(CTRL_X + 3.5, CTRL_Y + 1.0)}")
print(f"acc_o_0 local pos = {(GATE_X + 2.5, GATE_Y + 1.0)}")
print(f"acc_s_0 local pos = {(GATE_X + 4.5, GATE_Y + 1.0)}")
print("Saved gate_acc_isolated_test_blueprint.txt")
