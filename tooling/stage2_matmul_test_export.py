"""
First real building block of the Reshenie 21 sequencer: the reusable
matmul unit, tested in isolation on ONE real operation from the smoke-test
reference (stage2_smoke_ref.py) - QKV projection for position 0.

REBUILT after a real bug found the hard way (not caught the first time
because output was truncated with `Select-Object -Last 40`, which hid the
warnings - lesson: never truncate draftsman's stderr when checking for
warnings, Reshenie 22): origin_y=10 for the weight ROM put its own
horizontal relay row at y=0, landing exactly on t_ctr's tile (0,0) -
OverlappingObjectsWarning, silently missed. Fix here: every logical block
(control, weight ROM, x ROM, ALU, accumulators) gets a clearly separated
origin (100+ tiles apart) with an explicit bridge() between blocks, rather
than trusting small numeric offsets not to collide by luck.
"""

import json
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

with open("stage2_smoke_weights.json") as f:
    ref = json.load(f)

SCALE = 100
DIM = ref["dim"]
N_IN = DIM
N_OUT = 3 * DIM
SLOT = N_IN + 1
LEN = N_OUT * SLOT
K = 900  # bumped from 50 (Reshenie 25 RESUME POINT continuation): the manual
# repair pipeline (build, revive, repair-entities, repair-wires, each a
# clipboard-paste-and-confirm round trip with the user) took several real
# minutes end to end this session - by the time the last wire fix landed,
# t_ctr had already counted tens of thousands of ticks past LEN*K=3000,
# permanently missing the one-shot valid ROM-address window (t_ctr never
# wraps/resets, so a late fix can't retroactively fix an address sweep that
# already passed). K=900 gives a 900*60/60=900s (~15 min) window, generous
# margin over the repair pipeline's real-world duration.
# was 50, originally 8 - the whole valid sweep at K=8 lasts only
# 8 real seconds, too short to actually WATCH what happens live via manual/
# automated checks (every previous check only ever landed long after the
# sweep ended, frozen either empty or not - can't tell if that's a timing
# bug or just "checked too late"). At K=300, each address holds for 5
# real seconds and the full sweep takes ~5 minutes - enough to check
# in on it partway through and see real, live, in-range signals instead
# of only ever inspecting the aftermath.

PULSE_TICK = K // 2  # Reshenie 26 continuation: was K-1 (the LAST tick of
# each address's window, right up against the transition edge) - live
# per-firing tracing found a real, reproducible 1-tick transient glitch in
# mult's output that occurs at (or very near) every address transition, and
# a pulse sitting right on K-1 sometimes captures it instead of the settled
# value. Tried compensating with a fixed tick offset between O's and P's
# paths (see BOUNDARY_FUDGE history below) - that only relocated which
# term got corrupted, never eliminated it, confirming this is a transition-
# adjacent transient, not a simple constant relative skew to cancel out.
# Real fix: stop firing next to the edge - K//2 sits deep in the middle of
# a 900-tick hold, hundreds of ticks from either neighboring transition, so
# even several ticks of uncertainty in either signal's path can't reach it.

H1_POS0 = [-1.27, -0.3464, 1.501, 0.1155]
Wqkv = ref["Wqkv"]
bqkv = ref["bqkv"]


def q(x):
    return int(round(x * SCALE))


weight_rom = []
for out_idx_ in range(N_OUT):
    for in_idx_ in range(N_IN):
        weight_rom.append(q(Wqkv[in_idx_][out_idx_]))
    weight_rom.append(q(bqkv[out_idx_]))
assert len(weight_rom) == LEN

bp = Blueprint()
bp.label = "stage2 matmul unit test v2 (QKV proj, pos 0)"
RED, GREEN = "red", "green"
RELAY_HOP = 8
ROWS_PER_COL = 4
COL_SPACING = 4

_bridge_ctr = 0


def bridge(from_id, from_pos, to_pos, color, hop=RELAY_HOP):
    """Same proven helper as export_full.py/rom_capacity_stress_export.py -
    chain of signal-each relays, each hop <= hop tiles. Returns hop count
    too (Reshenie 22 timing-skew fix needs exact tick-latency accounting -
    every relay/arithmetic/decider combinator in Factorio has EXACTLY 1
    tick of output latency, so hop count == tick delay along this chain)."""
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


def pad_delay(from_id, from_pos, n_ticks, color, origin, direction=(1, 0), spacing=RELAY_HOP):
    """Insert exactly n_ticks single-hop (1 tick each) relay combinators in
    a straight line from `origin`, to equalize total propagation delay
    between two signal paths that must arrive in sync at a shared gate.
    Reshenie 22 root cause: out_idx (O) reached the accumulator gate via a
    ~55-hop direct bridge from CTRL, while signal-P (W*X) reached the same
    gate via a much longer path through the weight/x ROM read+collect
    chains - dozens of ticks more. Since gate_j compares O to a constant
    j while P is added only when O==j, any nonzero *relative* skew larger
    than a single address's hold window (K ticks) means the two signals
    are never simultaneously valid for the same original address, and the
    gate permanently misses its contribution - explains why ALL 12
    accumulators read back as empty/zero. Fix: pad every path (in ticks,
    not tiles) to a common target length so everything feeding one gate
    has identical total hop-delay from t_ctr, by construction.
    `origin` must be within 9 tiles of `from_pos` (single direct hop, no
    surprise extra latency) and `direction` should point into empty space
    - spacing defaults to the same 8 tiles every other bridge() in this
    file uses, so the chain is exactly as sparse/collision-safe as the
    project's already-proven relay chains, not a dense cluster."""
    global _bridge_ctr
    if n_ticks <= 0:
        return from_id, from_pos
    ox, oy = origin
    dx, dy = direction
    prev_id, prev_pos = from_id, from_pos
    for i in range(n_ticks):
        pos = (ox + dx * i * spacing, oy + dy * i * spacing)
        _bridge_ctr += 1
        bid = f"pad_{_bridge_ctr}"
        e = ArithmeticCombinator(id=bid, position=pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
        bp.entities.append(e)
        bp.add_circuit_connection(color, prev_id, bid, side_1="output", side_2="input")
        prev_id, prev_pos = bid, pos
    return prev_id, prev_pos


def build_addressed_rom(name, values, cond_signal, out_signal, origin_x, origin_y):
    """Places the ROM cells + internal relay/collector chains, does NOT
    connect to any external broadcast source - caller bridges in
    separately (Reshenie 22 fix: no more assuming the source is close)."""
    n = len(values)
    n_cols = math.ceil(n / ROWS_PER_COL)
    col_entry = {}
    for col in range(n_cols):
        rows_here = min(ROWS_PER_COL, n - col * ROWS_PER_COL)
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
        for i in range(col * ROWS_PER_COL, min((col + 1) * ROWS_PER_COL, n)):
            row = i - col * ROWS_PER_COL
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
        entry_pos = (origin_x + col * COL_SPACING + 1, origin_y + entry_dy)
        bp.add_circuit_connection(GREEN, hid, entry_id, side_1="output", side_2="input")
    broadcast_entry_id, broadcast_entry_pos = f"{name}_hrelay_0", (origin_x, origin_y - RELAY_HOP - 2)

    col_collectors = {}
    for col in range(n_cols):
        rows_here = min(ROWS_PER_COL, n - col * ROWS_PER_COL)
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
        for i in range(col * ROWS_PER_COL, min((col + 1) * ROWS_PER_COL, n)):
            row = i - col * ROWS_PER_COL
            ry = row * 2
            nearest_rid, _ = min(hops, key=lambda hy: abs(hy[1] - ry))
            bp.add_circuit_connection(RED, f"{name}_read_{i}", nearest_rid, side_1="output", side_2="input")

    # BUG FOUND (Reshenie 22 continuation), two parts:
    # (1) this chain used to wire col_collectors[k].output -> col_collectors
    # [k-1].input, cascading DOWN into col_collectors[0] (the true summing
    # sink, by induction) - but the function RETURNED the loop's final
    # `prev`/`cur` (col_collectors[n_cols-1]) instead, a leaf that only
    # ever carries ITS OWN column's local value. mult read W (or X) as 0
    # for every address outside the last column's tiny range, which
    # explains why every accumulator settled on empty/zero.
    # (2) even fixed to return the true sink, that direction makes total
    # latency (broadcast_entry -> sink) grow with column index c: the
    # address takes c hops to reach column c (hrelay chain), and column
    # c's value then ALSO needs c hops to cascade back down to the sink -
    # both terms grow with c instead of cancelling, so different addresses
    # arrive at wildly different times (up to ~2*(n_cols-1) ticks apart).
    # Fix for both: cascade the collector chain in the SAME direction as
    # the address broadcast (0 -> n_cols-1, low column feeds the next),
    # with the sink at col_collectors[n_cols-1]. Now address-in delay (c)
    # and value-out delay (n_cols-1-c) sum to the constant (n_cols-1) for
    # every column - one fixed, address-independent latency for the whole
    # ROM, not just a "which node do I return" fix.
    prev, prev_pos = col_collectors[0]
    for col in range(1, n_cols):
        cur, cur_pos = col_collectors[col]
        bp.add_circuit_connection(RED, prev, cur, side_1="output", side_2="input")
        prev, prev_pos = cur, cur_pos
    return (broadcast_entry_id, broadcast_entry_pos), (prev, prev_pos)


# ---- well-separated block origins (Reshenie 22: generous gaps, bridge()
# between them, never rely on small numbers not colliding by luck) ----
CTRL_X, CTRL_Y = 0, 0
WROM_X, WROM_Y = 0, 200
XROM_X, XROM_Y = 300, 200
ALU_X, ALU_Y = 150, 400

t_ctr = ArithmeticCombinator(id="t_ctr", position=(CTRL_X + 0.5, CTRL_Y + 1.0), first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T")
bp.entities.append(t_ctr)
addr = ArithmeticCombinator(id="addr", position=(CTRL_X + 0.5, CTRL_Y + 4.0), first_operand="signal-T", operation="/", second_operand=K, output_signal="signal-N")
bp.entities.append(addr)
bp.add_circuit_connection(RED, "t_ctr", "t_ctr", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "t_ctr", "addr", side_1="output", side_2="input")

in_idx = ArithmeticCombinator(id="in_idx", position=(CTRL_X + 3.5, CTRL_Y + 4.0), first_operand="signal-N", operation="%", second_operand=SLOT, output_signal="signal-I")
bp.entities.append(in_idx)
out_idx = ArithmeticCombinator(id="out_idx", position=(CTRL_X + 3.5, CTRL_Y + 6.0), first_operand="signal-N", operation="/", second_operand=SLOT, output_signal="signal-O")
bp.entities.append(out_idx)
bp.add_circuit_connection(RED, "addr", "in_idx", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "addr", "out_idx", side_1="output", side_2="input")

# Pulse (Reshenie 22 continuation, second bug found in this same block):
# gate_j originally only checked signal-O == j, which stays true for the
# WHOLE 40-tick (SLOT*K) out_idx block, not just once - so acc_j would add
# the held signal-P value on EVERY one of those ticks (accumulating each
# weight*input K=8 times over, not once). Fixed the same way the very
# first demo (proc_demo_export.py, Reshenie 14) did it: a `pulse`-style
# flag that's true for exactly 1 tick per address (tmod == PULSE_TICK,
# now mid-window rather than the last tick - see Reshenie 26), ANDed into
# gate_j's condition. tmod must
# be padded to the SAME depth as out_idx (2 ticks from t_ctr: t_ctr->addr
# ->out_idx) before merging, or the pulse and the O==j window would drift
# apart from each other over time same as the O/P bug above.
tmod = ArithmeticCombinator(id="tmod", position=(CTRL_X + 6.5, CTRL_Y + 1.0), first_operand="signal-T", operation="%", second_operand=K, output_signal="signal-M")
bp.entities.append(tmod)
bp.add_circuit_connection(RED, "t_ctr", "tmod", side_1="output", side_2="input")
tmod2 = ArithmeticCombinator(id="tmod2", position=(CTRL_X + 6.5, CTRL_Y + 3.0), first_operand="signal-M", operation="+", second_operand=0, output_signal="signal-M")
bp.entities.append(tmod2)
bp.add_circuit_connection(RED, "tmod", "tmod2", side_1="output", side_2="input")

def bridge_to(from_id, from_pos, target_id, target_pos, color, standoff=3, pad_ticks=0, pad_origin=None, pad_direction=(1, 0)):
    """bridge() landing EXACTLY on an existing entity's position creates a
    literal duplicate at that tile (found the hard way here) - stop one
    short hop early instead, then make a normal (<9 tile) direct
    connection into the real target. Returns total hop count (=tick
    latency) for this leg, since every relay/combinator here is 1 tick.
    pad_ticks (Reshenie 22 timing-skew fix) inserts that many EXTRA 1-tick
    relays (via pad_delay, placed close to `from_pos` so it contributes
    exactly pad_ticks hops, no surprise overhead) before the final hop -
    used to make two signals that must arrive together at a shared
    compare/gate have equal total latency from their common source.
    pad_origin must be within 9 tiles of from_pos; pad_direction picks
    which way the padding chain extends (caller's job to point it at
    empty space)."""
    prev_id, prev_pos, hops = from_id, from_pos, 0
    if pad_ticks > 0:
        origin = pad_origin or (from_pos[0], from_pos[1] + RELAY_HOP * 0.9)
        prev_id, prev_pos = pad_delay(from_id, from_pos, pad_ticks, color, origin, direction=pad_direction)
        hops += pad_ticks
    tx, ty = target_pos
    fx, fy = prev_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist <= standoff + 1.5:
        # either close enough to connect directly, or (found the hard way
        # with x_final) close enough that the standoff-short last relay
        # would itself land within collision range of the target - both
        # cases resolved the same way, a direct connection.
        bp.add_circuit_connection(color, prev_id, target_id, side_1="output", side_2="input")
        return hops + 1
    t = (dist - standoff) / dist
    stop_pos = (fx + (tx - fx) * t, fy + (ty - fy) * t)
    last_id, _, n_hops = bridge(prev_id, prev_pos, stop_pos, color)
    bp.add_circuit_connection(color, last_id, target_id, side_1="output", side_2="input")
    return hops + n_hops + 1


def solve_pad_ticks(source_pos, pad_origin, direction, target_pos, target_total, fixed_prefix,
                     final_hop_fn, spacing=RELAY_HOP, max_n=2000):
    """Find the SMALLEST n (>=0) such that padding n ticks from pad_origin (in
    `direction`, `spacing` tiles apart) before bridging on to target_pos gives
    a total delay >= target_total. Replaces the earlier "pad_ticks = target -
    natural" guess, which assumed 1 tick of padding = 1 tick of extra delay -
    wrong in practice (found the hard way): moving the chain's START point
    changes the length of the FINAL bridge back to the target too, and that
    change is neither 0 (pure cancellation) nor a clean 1:1 or 2:1 ratio in
    general - it depends on the actual geometry. This just tries increasing
    n and re-measures the real total (pure arithmetic, no entities built)
    until the target is actually met, instead of trusting an assumed ratio.
    `final_hop_fn` must match whichever mechanism actually closes the last
    leg at the real build site: hops_needed (bridge_to's standoff+direct-
    connect math) or hops_for_bridge (bridge()'s plain math, no standoff)."""
    for n in range(0, max_n):
        if n == 0:
            end_pos = source_pos
        else:
            end_pos = (pad_origin[0] + direction[0] * (n - 1) * spacing,
                       pad_origin[1] + direction[1] * (n - 1) * spacing)
        total = fixed_prefix + n + final_hop_fn(end_pos, target_pos)
        if total >= target_total:
            return n, total
    return max_n, None


def hops_needed(from_pos, target_pos, standoff=3):
    """Same hop-count math as bridge_to(), without building entities - lets
    us decide padding amounts before committing to geometry."""
    fx, fy = from_pos
    tx, ty = target_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist <= standoff + 0.5:
        return 1
    return max(1, math.ceil((dist - standoff) / RELAY_HOP)) + 1


def hops_for_bridge(from_pos, to_pos, hop=RELAY_HOP):
    """Same hop-count math as bridge(), without building entities."""
    dist = math.hypot(to_pos[0] - from_pos[0], to_pos[1] - from_pos[1])
    if dist < 1e-9:
        return 0
    return max(1, math.ceil(dist / hop))


# ---- ROM blocks, built at their own clear origins, bridged in from addr/
# in_idx. Timing accounting below (Reshenie 22 continuation) computes each
# path's total tick-latency from its true source (addr or in_idx) and pads
# every shorter path so everything that gets compared/merged/multiplied
# downstream (bias vs ROM-X at x_final, W vs X at mult, O vs P at gate_j)
# arrives with EQUAL total delay - otherwise each comparison is checking
# stale-vs-fresh data for DIFFERENT original addresses and never lines up
# (this, plus the collector-direction bug above, is why every accumulator
# read back empty before this fix). ----
w_entry, w_collect_info = build_addressed_rom("w", weight_rom, "signal-N", "signal-W", WROM_X, WROM_Y)
addr_pos = (CTRL_X + 0.5, CTRL_Y + 4.0)
addr_to_w_hops = bridge_to("addr", addr_pos, w_entry[0], w_entry[1], GREEN)

# bias folded in as x ROM's own (N_IN)'th value (Reshenie 22 continuation:
# a separate bias_flag decider, gated on in_idx==N_IN and merged with the
# ROM's collector output at x_final, needed its own padded path kept in
# lockstep with the ROM branch - one more synchronized-arrival requirement
# to get right. Not needed at all if the bias constant just lives in the
# ROM at the address in_idx already visits for it - SLOT=N_IN+1 means
# in_idx legitimately reaches N_IN once per output, so this is a real
# address, not a special case) ----
x_values = [q(v) for v in H1_POS0] + [SCALE]
x_entry, x_collect_info = build_addressed_rom("x", x_values, "signal-I", "signal-X", XROM_X, XROM_Y)
in_idx_pos = (CTRL_X + 3.5, CTRL_Y + 4.0)
in_idx_to_x_hops = bridge_to("in_idx", in_idx_pos, x_entry[0], x_entry[1], GREEN)

n_cols_w = math.ceil(len(weight_rom) / ROWS_PER_COL)
n_cols_x = math.ceil(len(H1_POS0) / ROWS_PER_COL)
w_internal, x_internal = n_cols_w + 3, n_cols_x + 3  # constant now (see build_addressed_rom fix)
L_W_total = addr_to_w_hops + w_internal    # addr's output -> w_collect's output, ticks
L_X_total = in_idx_to_x_hops + x_internal  # in_idx's output -> x_collect's output, ticks
print(f"[timing] L_W_total={L_W_total} (addr->w_entry {addr_to_w_hops} + internal {w_internal})")
print(f"[timing] L_X_total={L_X_total} (in_idx->x_entry {in_idx_to_x_hops} + internal {x_internal})")

# ---- ALU block: x collect (bias is just x ROM's own N_IN'th value now), multiply ----
x_final_pos = (ALU_X + 3.5, ALU_Y + 1.0)
mult_pos = (ALU_X + 0.5, ALU_Y + 4.0)
xc_id, xc_pos = x_collect_info

x_final = ArithmeticCombinator(id="x_final", position=x_final_pos, first_operand="signal-X", operation="+", second_operand=0, output_signal="signal-X")
bp.entities.append(x_final)
xc_to_xfinal_hops = bridge_to(xc_id, xc_pos, "x_final", x_final_pos, RED)

X_ready = 1 + L_X_total + xc_to_xfinal_hops + 1  # +1 addr->in_idx, +1 x_final's own compute; relative to addr
print(f"[timing] X ready at mult input (rel. addr) = {X_ready}")

# W and X must also arrive at mult with equal total delay (mult always
# computes W*X, no gating - a stale W paired with a fresh X, or vice
# versa, silently multiplies mismatched values).
wc_id, wc_pos = w_collect_info
wc_to_mult_natural = hops_needed(wc_pos, mult_pos, standoff=6)
W_ready_natural = L_W_total + wc_to_mult_natural
target_mult_ready = max(W_ready_natural, X_ready)
w_pad_origin = (wc_pos[0] + RELAY_HOP * 0.9, wc_pos[1])
w_pad, _ = solve_pad_ticks(wc_pos, w_pad_origin, (1, 0), mult_pos, target_mult_ready, L_W_total,
                            lambda p, t: hops_needed(p, t, standoff=6))

mult = ArithmeticCombinator(id="mult", position=mult_pos, first_operand="signal-W", operation="*", second_operand="signal-X", output_signal="signal-P")
bp.entities.append(mult)
# Pad at CONSTANT y = wc_pos's own y: this row never dips into WROM's
# y~190-210 band (it stays exactly on it, past the ROM's own columns
# which end at x~59). w_pad itself is now solved exactly (solve_pad_ticks)
# rather than assumed 1:1, since padding here also changes the length of
# the final bridge back to mult - found the hard way that assumption was
# wrong by a wide margin for the O/P padding below.
wc_to_mult_hops = bridge_to(wc_id, wc_pos, "mult", mult_pos, RED, standoff=6, pad_ticks=w_pad,
                             pad_origin=w_pad_origin, pad_direction=(1, 0))
bp.add_circuit_connection(RED, "x_final", "mult", side_2="input")
W_ready = L_W_total + wc_to_mult_hops
print(f"[timing] W ready at mult input (rel. addr) = {W_ready} (padded {w_pad}), X ready = {X_ready}")

P_ready = max(W_ready, X_ready) + 1  # mult's own compute tick; relative to addr
print(f"[timing] P ready at mult output (rel. addr) = {P_ready}")

# ---- 12 gated accumulators, single row, spine-with-taps (same proven
# pattern as the ROM's hrelay->vrelay: a relay line runs ABOVE the row,
# each slot taps the NEAREST spine point with a short direct connection -
# not a 2D grid with fan-out hubs, which kept colliding with its own
# entities in three separate ways before this rewrite) ----
ACC_X, ACC_Y = ALU_X, ALU_Y + 20
SLOT_W = 8  # gate,acc,rescale at +0.5,+2.5,+4.5 - 3.5 tile gap before next slot, safe
SPINE_Y = ACC_Y - 3  # clearly above the row (row entities sit at ACC_Y+1.0)

out_idx_pos = (CTRL_X + 3.5, CTRL_Y + 6.0)
oidx_entry_target = (ACC_X, SPINE_Y)
mult_entry_target = (ACC_X, SPINE_Y - 2)
mult_entry_natural = hops_for_bridge(mult_pos, mult_entry_target)

# out_idx and tmod2 (both exactly 2 ticks from t_ctr - see the pulse
# comment above) merge onto one GREEN network here, 1 tick before the
# spine starts, so signal-O and the pulse flag (signal-M) travel the
# IDENTICAL physical chain from here on - no separate padding/sync needed
# between them, only between this merged pair and P (below).
o_merge_pos = (out_idx_pos[0] + 1.0, out_idx_pos[1])
o_merge = ArithmeticCombinator(id="o_merge", position=o_merge_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(o_merge)
bp.add_circuit_connection(GREEN, "out_idx", "o_merge", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "tmod2", "o_merge", side_1="output", side_2="input")
oidx_entry_natural = hops_for_bridge(o_merge_pos, oidx_entry_target)

# O (out_idx+pulse) and P (mult's output) must reach gate_j with EQUAL
# total delay from addr - the per-slot tap loop below adds exactly 1 hop
# per slot to BOTH spines in lockstep, so only the base (pre-loop) delay
# needs equalizing here for every slot to line up.
base_O_natural = 1 + 1 + oidx_entry_natural   # +1 addr->out_idx, +1 out_idx->o_merge
base_P_natural = P_ready + mult_entry_natural
target_base = max(base_O_natural, base_P_natural)

# Reshenie 25/26 continuation, attempts 1-2 (both abandoned): tried nudging
# P's total delay relative to O by a fixed number of ticks (BOUNDARY_FUDGE),
# reasoning the x-ROM's undersized trailing column (5 values/ROWS_PER_COL=4
# = a 4-row + a 1-row column) gives it 1 less internal hop than the
# "constant delay regardless of column" formula assumes. Attempt 1 (fudge
# folded into a SHARED target) changed nothing (reproduced the original bug
# bit-for-bit - target_base's max() absorbs any nudge to either natural
# value). Attempt 2 (separate O/P targets, P deliberately +1) DID change
# behavior, but not into a fix: the misattributed term moved from k=0 (the
# out_idx boundary) to k=3 (a boundary INSIDE a window, between real
# weight-ROM columns) - proof this is some kind of transient glitch at
# address-transition ticks that a small path-delay nudge only relocates,
# never eliminates. Real fix below: don't chase an exact tick offset at
# all - move the pulse itself off the transition edge entirely, deep into
# the middle of each address's long K-tick hold, where several ticks of
# uncertainty in either direction can't reach any transition-adjacent
# glitch. O and P are back to the original, PROVEN-exact equal target.
target_O = target_base
target_P = target_base

# o_merge pads at constant y (its own row) growing -x: every other block in
# this design is either at a much larger y (ROMs y~190+, ALU/ACC y~400+)
# reached by lines that move away from y=6 as x grows, or at small x (CTRL
# itself, x<4) - so this whole row stays empty no matter how far it
# extends. mult pads straight left (-x) too: ACC sits to mult's
# right/below, CTRL/ROMs are all at different y, so -x at mult's own y is
# clear too. Both o_pad and p_pad are now solved exactly (solve_pad_ticks)
# instead of assumed 1:1 - found the hard way that assumption overshot by
# 15 ticks here (requested 29, actually got +44), because moving the pad
# chain's start point also changes the length of the fresh diagonal bridge
# back to the real target, and that's neither 0 nor a clean ratio.
o_pad_origin = (o_merge_pos[0] - RELAY_HOP * 0.9, o_merge_pos[1])
p_pad_origin = (mult_pos[0] - RELAY_HOP * 0.9, mult_pos[1])


def achievable_totals(source_pos, pad_origin, direction, target_pos, fixed_prefix, max_n=200, spacing=RELAY_HOP):
    """Pure math (no entities) - for every pad count n, the EXACT total delay
    pad_delay(n)+bridge-to-target would produce. solve_pad_ticks only finds
    the smallest n reaching >= a single target, which can overshoot it by a
    geometry-dependent (non-1) amount - found the hard way (Reshenie 25
    continuation) that this let O and P land on DIFFERENT exact totals
    (88 vs 87) even though both aimed at the same target_base, silently
    reintroducing the very off-by-one boundary bug this exists to fix.
    Returns {total: n} for every achievable total in range, so the caller
    can pick a total BOTH sides can hit exactly, instead of hoping a single
    shared target happens to be reachable by both independently."""
    out = {}
    for n in range(0, max_n):
        end_pos = source_pos if n == 0 else (pad_origin[0] + direction[0] * (n - 1) * spacing,
                                              pad_origin[1] + direction[1] * (n - 1) * spacing)
        total = fixed_prefix + n + hops_for_bridge(end_pos, target_pos)
        out.setdefault(total, n)  # keep the SMALLEST n for a given total
    return out


o_achievable = achievable_totals(o_merge_pos, o_pad_origin, (-1, 0), oidx_entry_target, 2)
p_achievable = achievable_totals(mult_pos, p_pad_origin, (-1, 0), mult_entry_target, P_ready)
o_exact = sorted(t for t in o_achievable if t >= target_O)
p_exact = sorted(t for t in p_achievable if t >= target_P)
assert o_exact and p_exact, "no exact achievable total found - widen max_n"
final_O = o_exact[0]
final_P = p_exact[0]
o_pad = o_achievable[final_O]
p_pad = p_achievable[final_P]
print(f"[timing] base_O_natural={base_O_natural} (pad {o_pad}), base_P_natural={base_P_natural} (pad {p_pad}), "
      f"target_O={target_O} EXACT={final_O}, target_P={target_P} EXACT={final_P}")

if o_pad > 0:
    pad_id, pad_pos = pad_delay("o_merge", o_merge_pos, o_pad, GREEN, o_pad_origin, direction=(-1, 0))
    oidx_spine, oidx_pos, o_final_hops = bridge(pad_id, pad_pos, oidx_entry_target, GREEN)
    actual_base_O = 2 + o_pad + o_final_hops
else:
    oidx_spine, oidx_pos, o_final_hops = bridge("o_merge", o_merge_pos, oidx_entry_target, GREEN)
    actual_base_O = 2 + o_final_hops

if p_pad > 0:
    pad_id2, pad_pos2 = pad_delay("mult", mult_pos, p_pad, RED, p_pad_origin, direction=(-1, 0))
    mult_spine, mult_spine_pos, p_final_hops = bridge(pad_id2, pad_pos2, mult_entry_target, RED)
    actual_base_P = P_ready + p_pad + p_final_hops
else:
    mult_spine, mult_spine_pos, p_final_hops = bridge("mult", mult_pos, mult_entry_target, RED)
    actual_base_P = P_ready + p_final_hops
assert actual_base_O == final_O and actual_base_P == final_P and actual_base_O == actual_base_P, \
    (actual_base_O, actual_base_P, final_O, final_P)
print(f"[timing-verify] actual_base_O={actual_base_O}, actual_base_P={actual_base_P} (EXACT match)")

oidx_taps, mult_taps = [(oidx_spine, oidx_pos)], [(mult_spine, mult_spine_pos)]
for j in range(1, N_OUT):
    tap_x = ACC_X + j * SLOT_W
    oidx_spine, oidx_pos, _ = bridge(oidx_spine, oidx_pos, (tap_x, SPINE_Y), GREEN)
    oidx_taps.append((oidx_spine, oidx_pos))
    mult_spine, mult_spine_pos, _ = bridge(mult_spine, mult_spine_pos, (tap_x, SPINE_Y - 2), RED)
    mult_taps.append((mult_spine, mult_spine_pos))

for j in range(N_OUT):
    gx = ACC_X + j * SLOT_W
    gy = ACC_Y
    gate = DeciderCombinator(
        id=f"gate_{j}", position=(gx + 0.5, gy + 1.0),
        conditions=[
            DeciderCombinator.Condition(first_signal="signal-O", comparator="=", constant=j, compare_type="and"),
            DeciderCombinator.Condition(first_signal="signal-M", comparator="=", constant=PULSE_TICK, compare_type="and"),
        ],
        outputs=[DeciderCombinator.Output(signal="signal-P", copy_count_from_input=True)],
    )
    bp.entities.append(gate)
    bp.add_circuit_connection(RED, mult_taps[j][0], f"gate_{j}", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, oidx_taps[j][0], f"gate_{j}", side_1="output", side_2="input")

    acc = ArithmeticCombinator(id=f"acc_{j}", position=(gx + 2.5, gy + 1.0), first_operand="signal-A", operation="+", second_operand="signal-P", output_signal="signal-A")
    bp.entities.append(acc)
    bp.add_circuit_connection(RED, f"acc_{j}", f"acc_{j}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"gate_{j}", f"acc_{j}", side_1="output", side_2="input")

    rescale = ArithmeticCombinator(id=f"out_{j}", position=(gx + 4.5, gy + 1.0), first_operand="signal-A", operation="/", second_operand=SCALE, output_signal="signal-A")
    bp.entities.append(rescale)
    bp.add_circuit_connection(RED, f"acc_{j}", f"out_{j}", side_1="output", side_2="input")

# ---- power: generous lattice, reuse the fast approach from Reshenie 15 ----
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


# (found by the user reviewing the generated blueprint, not caught by me:
# this session's O/P timing-skew padding pushed the bounding box out to
# hundreds of empty tiles in several directions - o_pad alone reaches
# x~-227 - and a naive full-bbox substation lattice blankets ALL of that
# empty territory too, not just the actual logic footprint. Same waste
# export_full.py already found and fixed once (Reshenie 11's "wasteful
# lattice" note) - ported the same `near_power_demand` pre-filter here so
# lattice points with nothing nearby to power are skipped outright,
# instead of being generated and then never actually needed.)
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
with open("stage2_matmul_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)

print(f"Entities: {len(bp.entities)}")
print(f"LEN={LEN}, settle time = {LEN*K} ticks minimum")
expected = []
for out_idx_ in range(N_OUT):
    s = sum(Wqkv[i][out_idx_] * H1_POS0[i] for i in range(N_IN)) + bqkv[out_idx_]
    expected.append(round(s, 4))
print(f"Expected qkv[0] fixed-point (x{SCALE}): {[q(e) for e in expected]}")
print(f"Expected qkv[0] real: {expected}")
print("Saved stage2_matmul_test_blueprint.txt")
