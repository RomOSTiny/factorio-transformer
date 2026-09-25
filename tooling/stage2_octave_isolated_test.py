"""
Isolated test of the NEW piece needed for the LayerNorm block (Reshenie 21
plan): the rsqrt lookup-table ADDRESS computation (which octave o and which
subbucket s a given var+eps value falls into), decoupled from LayerNorm's
own sum/mean/var/normalize logic and from the (already-proven, Reshenie 26)
timing-padding machinery. Same discipline the matmul block's own postmortem
(Reshenie 24) called out as skipped and costly - test the genuinely NEW
mechanism small, BEFORE wiring it into a much bigger block.

Design decision worth restating here (see stage2_layernorm_ref.py for the
full reasoning): o is found via 30 PARALLEL threshold comparisons (value
>= 2^(k+1) for k=0..29, summed) rather than a serial "find highest set bit"
shift-chain. A serial chain would need its own internal tick-latency
accounting (like every ROM/ALU path in stage2_matmul_test_export.py) - the
parallel form reuses the exact "N independent deciders + shared spine
collector" shape already proven by the classifier's argmax/syllable
detectors and by this project's own gate_j/acc_j accumulator row, so it
adds a genuinely new COMPARISON but not a new SYNCHRONIZATION mechanism.

Test values chosen to hit interesting cases (computed with
stage2_layernorm_ref.rsqrt_addr, which implements this exact same integer
algorithm in Python - see that file for expected o/s per value):
  1          -> o=0,  s=0   (smallest possible vpe_fp; also exercises the
                              half_lower==0 division-by-zero-safe path)
  255        -> o=7,  s=31  (just below a power of 2 - top of its octave)
  256        -> o=8,  s=0   (exactly a power of 2 - bottom of its octave)
  472        -> o=8,  s=27  (the REAL value this session's LayerNorm smoke
                              test will actually need, from x[0] in
                              stage2_smoke_weights.json)
  1000000    -> o=19, s=29  (mid-range, closer to the real trained model's
                              actual var+eps scale at SCALE=1000)
  1073741824 -> o=30, s=0   (=2^30, the top-clamped octave - exercises the
                              int32-safe upper bound from stage2_layernorm_ref.py)
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

TEST_VALS = [1, 255, 256, 472, 1000000, 1073741824]
EXPECTED = [(0, 0), (7, 31), (8, 0), (8, 27), (19, 29), (30, 0)]  # from stage2_layernorm_ref.rsqrt_addr
N_TEST = len(TEST_VALS)

BUCKETS_PER_OCTAVE = 32
OCTAVE_MIN = 0
OCTAVE_MAX = 30
N_OCT = OCTAVE_MAX - OCTAVE_MIN + 1
OCT_LOWER = [2 ** o for o in range(OCTAVE_MIN, OCTAVE_MAX + 1)]

K = 9000  # ticks/address - was 300 (30s total sweep for 6 addresses), bumped
# for the SAME reason matmul went 50->900 (Reshenie 25/26 continuation):
# the manual repair pipeline (build, revive, repair-entities, repair-wires,
# register-logger, each a clipboard-paste-and-confirm round trip) takes
# several real MINUTES end to end, not seconds - a short K meant t_ctr had
# already swept past every address's valid window before repair even
# finished, so a gate logger registered afterward could only ever see the
# frozen (already-corrupted-by-then, or just plain stale) aftermath, never
# the actual firings. K=9000 gives each address a 9000/60=150s (2.5 min)
# window, 900s (15 min) for the whole 6-address sweep - comfortably past
# this project's own observed repair-pipeline duration.
PULSE_TICK = K // 2

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "octave/subbucket LUT-address isolated test"

ROWS_PER_COL = 4
COL_SPACING = 4
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


def build_addressed_rom(name, values, cond_signal, out_signal, origin_x, origin_y, rows_per_col=ROWS_PER_COL):
    """Same proven mechanism as stage2_matmul_test_export.py's helper of the
    same name (broadcast address on cond_signal, private value on out_signal,
    kept on separate colors per Reshenie 14's rule), just parameterized by
    rows_per_col so a much longer ROM (oct_lower here doesn't need it, but
    the real LayerNorm block's 992-word rsqrt table will) doesn't need an
    absurdly wide layout."""
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


# ---- well-separated block origins (same discipline as Reshenie 22's fix:
# generous gaps, bridge() between them, never rely on small numbers not
# colliding by luck) ----
CTRL_X, CTRL_Y = 0, 0
VROM_X, VROM_Y = 0, 100
CMP_X, CMP_Y = 250, 0       # 30 threshold comparators
OLROM_X, OLROM_Y = 250, 150  # oct_lower ROM (31 words)
CALC_X, CALC_Y = 250, 300    # diff/half_lower/s/addr_rsqrt
ACC_X, ACC_Y = 250, 400      # per-test-case capture

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

# ---- value ROM: TEST_VALS, addressed directly by addr ----
v_entry, v_collect_info = build_addressed_rom("vrom", TEST_VALS, "signal-D", "signal-V", VROM_X, VROM_Y)
addr_pos = (CTRL_X + 0.5, CTRL_Y + 4.0)
bridge_to("addr", addr_pos, v_entry[0], v_entry[1], GREEN)
vc_id, vc_pos = v_collect_info
value_bc_pos = (CMP_X - 20 + 0.5, CMP_Y - 10)  # +0.5: integer local X on a
# position= entity gets shifted +0.5 at live placement (Reshenie 26) while
# an already-fractional interpolated relay hop nearby does NOT - found the
# hard way THIS session (v_local/ol_local below): a blueprint gap that
# passes draftsman's own overlap check in unshifted coordinates can still
# collide live once the shift is applied asymmetrically. Every position=
# call in this file now gets an explicit non-integer local X for exactly
# this reason, not just the two that got caught red-handed.
value_bc = ArithmeticCombinator(id="value_bc", position=value_bc_pos, first_operand="signal-V", operation="+", second_operand=0, output_signal="signal-V")
bp.entities.append(value_bc)
bridge_to(vc_id, vc_pos, "value_bc", value_bc_pos, RED)

# ---- 30 parallel threshold comparators (value >= 2^(k+1)). Broadcast side
# (signal-V reaching all 30) needs a real relay spine - 90 tiles end to end,
# far past the 9-tile direct-wire limit, same "bridge() spine with taps"
# shape as every ROM broadcast in this project.
#
# Collector side: an EARLIER draft daisy-chained the comparators' OUTPUTS
# directly to each other (cmp_k.output--cmp_{k+1}.output, no intermediate
# entity), reasoning that Factorio auto-sums same-named signals from
# multiple sources on one network - untested assumption, and the live
# per-tick log proved it wrong: o_collect never settled to a stable sum,
# it kept climbing for thousands of ticks (sometimes bleeding across an
# entire address boundary into the next test case's window), and each
# gate's captured "o" came out at EXACTLY 2^(address index) times the true
# value - a systematic, compounding error, not noise. Switched to the
# SAME proven collector shape build_addressed_rom's col_collectors already
# uses successfully (matmul, Reshenie 22-26): a dedicated RELAY entity per
# source, each one actually COMPUTING (reads its combined input via a *1
# multiply, writes a fresh output) rather than raw peer-to-peer output
# merging - chained hop-to-hop (collect_{k+1}.output -> collect_k.input,
# cascading DOWN to collect_0 as the true sink, matching Reshenie 23's
# "cascade in the same direction as the broadcast" fix), with each
# comparator's own contribution merging in via a direct connection to its
# own collect_k. Untested novel wiring replaced with the project's own
# already-proven pattern instead of debugging the untested one further. ----
SLOT_W = 3
SPINE_Y = CMP_Y - 3
bc_spine_target = (CMP_X, SPINE_Y)
bc_spine, bc_spine_pos, _ = bridge("value_bc", value_bc_pos, bc_spine_target, RED)

bc_taps = [(bc_spine, bc_spine_pos)]
for k in range(1, 30):
    tap_x = CMP_X + k * SLOT_W
    bc_spine, bc_spine_pos, _ = bridge(bc_spine, bc_spine_pos, (tap_x, SPINE_Y), RED)
    bc_taps.append((bc_spine, bc_spine_pos))

for k in range(30):
    cx = CMP_X + k * SLOT_W
    cy = CMP_Y
    cmp_e = DeciderCombinator(
        id=f"cmp_{k}", position=(cx + 0.5, cy + 1.0),
        conditions=[DeciderCombinator.Condition(first_signal="signal-V", comparator=">=", constant=2 ** (k + 1))],
        outputs=[DeciderCombinator.Output(signal="signal-I", copy_count_from_input=False, constant=1)],
    )
    bp.entities.append(cmp_e)
    bp.add_circuit_connection(RED, bc_taps[k][0], f"cmp_{k}", side_1="output", side_2="input")

# Build collect_29 (leaf, no higher neighbor) first, then collect_28..collect_0
# in descending order, so each new collect_k can immediately wire to the
# already-built collect_{k+1}.
collect_ids = {}
for k in range(29, -1, -1):
    cx = CMP_X + k * SLOT_W
    cy = CMP_Y
    rid = f"collect_{k}"
    e = ArithmeticCombinator(id=rid, position=(cx + 0.5, cy + 3.0), first_operand="signal-I", operation="*", second_operand=1, output_signal="signal-I")
    bp.entities.append(e)
    collect_ids[k] = rid
    bp.add_circuit_connection(RED, f"cmp_{k}", rid, side_1="output", side_2="input")
    if k < 29:
        bp.add_circuit_connection(GREEN, collect_ids[k + 1], rid, side_1="output", side_2="input")

# Renames signal-I (collect_0's true total, by induction over the whole
# chain) to signal-O for everything downstream, same role as matmul's
# x_final/value_bc rename-relay.
o_collect_pos = (CMP_X - 15 + 0.5, CMP_Y + 3.0)  # well clear to the left of
# collect_0 AND off the SPINE_Y=-3 row the broadcast spine occupies - an
# earlier placement near (CMP_X-4, SPINE_Y-2) put o_collect's own downstream
# bridges (to the oct_lower ROM, to the ACC block) on a path back through
# the comparator row's own territory, colliding with collect_k/cmp_k.
o_collect = ArithmeticCombinator(id="o_collect", position=o_collect_pos, first_operand="signal-I", operation="+", second_operand=0, output_signal="signal-O")
bp.entities.append(o_collect)
bridge_to("collect_0", (CMP_X + 0.5, CMP_Y + 3.0), "o_collect", o_collect_pos, RED, standoff=3, hop=6)

# ---- oct_lower ROM (31 words: 2^0..2^30), addressed by o_collect (signal-O) ----
ol_entry, ol_collect_info = build_addressed_rom("olrom", OCT_LOWER, "signal-O", "signal-L", OLROM_X, OLROM_Y)
bridge_to("o_collect", o_collect_pos, ol_entry[0], ol_entry[1], GREEN, hop=8)
olc_id, olc_pos = ol_collect_info

# ---- diff = value - oct_lower; half_lower = oct_lower // 32;
#      s = diff // half_lower (Factorio's div-by-zero-safe convention gives
#      0 when half_lower==0, i.e. o<5 - see stage2_layernorm_ref.py) ----
#
# olc_id (signal-L) and value_bc (signal-V) each feed TWO nearby targets
# here (diff_e and half_e; diff_e and the comparator spine, respectively) -
# bridging point-to-point from one source to each target independently
# produced overlapping relay hops (same fan-out collision just fixed in the
# ACC section, Reshenie 8's class of bug). Fixed the same way: bridge ONCE
# to a local junction near this block, then short (<9 tile) direct
# connections from there to each actual consumer.
ol_local_pos = (CALC_X - 5 + 0.5, CALC_Y + 1.0)  # +0.5, see value_bc_pos comment
ol_local = ArithmeticCombinator(id="ol_local", position=ol_local_pos, first_operand="signal-L", operation="+", second_operand=0, output_signal="signal-L")
bp.entities.append(ol_local)
bridge_to(olc_id, olc_pos, "ol_local", ol_local_pos, GREEN)

v_local_pos = (CALC_X - 5 + 0.5, CALC_Y - 2.0)  # +0.5, see value_bc_pos comment -
# this specific entity is where the live collision was actually caught: a
# relay hop from bridge_to("value_bc",...) landed at local x~245.71 (already
# fractional, no shift applied), while v_local's own local x=245 (integer)
# shifted to 245.5 once placed - shrinking their blueprint-time gap of 0.71
# tiles down to 0.21 tiles in the live world, well inside collision range,
# and reproducibly killing that relay's ghost on revive across 3 separate
# rebuilds before this was diagnosed.
v_local = ArithmeticCombinator(id="v_local", position=v_local_pos, first_operand="signal-V", operation="+", second_operand=0, output_signal="signal-V")
bp.entities.append(v_local)
bridge_to("value_bc", value_bc_pos, "v_local", v_local_pos, RED)

diff_pos = (CALC_X + 0.5, CALC_Y + 1.0)
diff_e = ArithmeticCombinator(id="diff_e", position=diff_pos, first_operand="signal-V", operation="-", second_operand="signal-L", output_signal="signal-F")
bp.entities.append(diff_e)
# BUG FOUND (this session, live in-game): every connection below used to omit
# side_1, which draftsman does NOT default to "output" as every other call
# in this file explicitly sets it to - confirmed empirically by decoding the
# built blueprint's own wire list and querying the live entities' actual
# wire_connector_id, both showed side_1 landing on the INPUT connector
# instead. Harmless for v_local/ol_local specifically (their op is a pure
# X+0 passthrough, so their INPUT network already carries the same value
# their OUTPUT would have recomputed) but NOT harmless here: diff_e's INPUT
# network never carries signal-F (that's diff_e's OUTPUT only) and half_e's
# INPUT never carries the divided signal-L (that's half_e's OUTPUT) - so
# s_e was reading two networks that never had its actual operands on them,
# silently computing s=0 for every single test case regardless of the true
# value. Every connection here now sets side_1="output" explicitly, same
# discipline bridge()/bridge_to() already followed throughout this file.
bp.add_circuit_connection(RED, "v_local", "diff_e", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "ol_local", "diff_e", side_1="output", side_2="input")

half_pos = (CALC_X + 3.5, CALC_Y + 1.0)
half_e = ArithmeticCombinator(id="half_e", position=half_pos, first_operand="signal-L", operation="/", second_operand=32, output_signal="signal-L")
bp.entities.append(half_e)
bp.add_circuit_connection(GREEN, "ol_local", "half_e", side_1="output", side_2="input")

s_pos = (CALC_X + 0.5, CALC_Y + 4.0)
s_e = ArithmeticCombinator(id="s_e", position=s_pos, first_operand="signal-F", operation="/", second_operand="signal-L", output_signal="signal-S")
bp.entities.append(s_e)
bp.add_circuit_connection(RED, "diff_e", "s_e", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "half_e", "s_e", side_1="output", side_2="input")

# ---- per-test-case capture: gate(addr==i AND tmod==PULSE_TICK) -> copy
# o_collect(signal-O) and s_e(signal-S) together (multi-output decider) into
# self-looping accumulators - same addr==j AND pulse pattern proven by
# gate_j/acc_j in stage2_matmul_test_export.py (Reshenie 26).
#
# Geometry, found the hard way (two earlier drafts): running o_collect and
# s_e through a shared "os_merge" combinator BEFORE spining out towards the
# ACC block creates a point where several long bridges from different
# distant origins all converge on one small neighborhood - their final
# hops land close to that shared point regardless of hop-size tricks
# (verified: giving each converging chain a different hop size, which DOES
# fix mid-path coincidences, left this exact collision unchanged, because
# the problem is geometric convergence at the endpoint, not discretization
# alignment along the way). Real fix, matching how matmul kept mult_taps
# and oidx_taps as two SEPARATE spines all the way to gate_j rather than
# merging them first: don't merge O-data and S-data at all - run TWO
# independent spines, each from its own true origin, both landing on
# gate_i's RED input (they coexist there automatically, being
# different-named signals - no explicit merge combinator needed, same as
# how W and X shared RED in stage2_matmul_test_export.py's mult). Only
# ctrl (D+M) still needs its own upfront merge, but that one merges two
# signals that originate at the SAME nearby location (CTRL block), so it
# never had this problem. ----
SLOT_W2 = 8
o_spine_target = (ACC_X, ACC_Y - 3)
# L-shaped route, not a direct diagonal: o_collect now lives to the LEFT of
# the CALC block (x~235.5) while ACC sits BELOW it (~250,397) - a straight
# line between them cuts diagonally through the CALC block's own territory
# (v_local/ol_local/diff_e/half_e/s_e all sit around x=245-254,y=298-310),
# found the hard way as a fresh collision right at that crossing. Going
# straight down first (staying at o_collect's own x, safely west of the
# CALC block for the whole descent) then across only once past it avoids
# ever entering that x/y region at all.
# descend at x=220, outside value_bc->v_local's diagonal x-range (230.5 to
# 245.5 as y goes from -10 to 298) - found the previous waypoint x (235.5,
# o_collect's own x) sat squarely inside that range and crossed it anyway.
# MUST be non-integer: this is a dead-straight vertical run of ~80 relay
# hops, so EVERY hop lands at exactly this x - an integer x here means
# EVERY ONE of those ~80 entities gets Reshenie 26's +0.5 live-placement
# shift, and the repair manifest (built from unshifted blueprint
# coordinates) then "discovers" all ~80 as missing and recreates them on
# top of the real ones - found this the hard way as entity-repair's
# created=75 on the first attempt with x=220 (an integer).
o_descent_x = 220.5
o_wp0_id, o_wp0_pos, _ = bridge("o_collect", o_collect_pos, (o_descent_x, o_collect_pos[1]), RED, hop=5)
o_wp1_id, o_wp1_pos, _ = bridge(o_wp0_id, o_wp0_pos, (o_descent_x, ACC_Y - 3), RED, hop=5)
o_spine, o_spine_pos, _ = bridge(o_wp1_id, o_wp1_pos, o_spine_target, RED, hop=5)
s_spine_target = (ACC_X, ACC_Y - 5)
s_spine, s_spine_pos, _ = bridge("s_e", s_pos, s_spine_target, RED, hop=7)
ctrl_spine_target = (ACC_X, ACC_Y - 7)
ctrl_spine, ctrl_spine_pos, _ = bridge("ctrl_merge", ctrl_merge_pos, ctrl_spine_target, GREEN, hop=9)

o_taps, s_taps, ctrl_taps = [(o_spine, o_spine_pos)], [(s_spine, s_spine_pos)], [(ctrl_spine, ctrl_spine_pos)]
for i in range(1, N_TEST):
    tap_x = ACC_X + i * SLOT_W2
    o_spine, o_spine_pos, _ = bridge(o_spine, o_spine_pos, (tap_x, ACC_Y - 3), RED)
    o_taps.append((o_spine, o_spine_pos))
    s_spine, s_spine_pos, _ = bridge(s_spine, s_spine_pos, (tap_x, ACC_Y - 5), RED, hop=7)
    s_taps.append((s_spine, s_spine_pos))
    ctrl_spine, ctrl_spine_pos, _ = bridge(ctrl_spine, ctrl_spine_pos, (tap_x, ACC_Y - 7), GREEN, hop=9)
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
            DeciderCombinator.Output(signal="signal-S", copy_count_from_input=True),
        ],
    )
    bp.entities.append(gate)
    bp.add_circuit_connection(RED, o_taps[i][0], f"gate_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, s_taps[i][0], f"gate_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, ctrl_taps[i][0], f"gate_{i}", side_1="output", side_2="input")

    # accumulator's own output signal MUST differ from the gate's output
    # signal name (signal-A/signal-B vs the gate's signal-O/signal-S) - same
    # self-loop-plus-gated-input shape as matmul's acc_j (first_operand=its
    # own running total, second_operand=the gate's one-shot value, both read
    # from the SAME shared network but distinguished by name so they don't
    # auto-sum into each other before this combinator even runs). Using the
    # SAME name for both (an earlier draft of this file did) would let the
    # network auto-sum the self-looped previous total with the gate's fresh
    # value BEFORE this combinator reads either operand, then this
    # combinator would add that already-merged value to itself again -
    # silently doubling the result on every firing.
    acc_o = ArithmeticCombinator(id=f"acc_o_{i}", position=(gx + 2.5, gy + 1.0), first_operand="signal-A", operation="+", second_operand="signal-O", output_signal="signal-A")
    bp.entities.append(acc_o)
    bp.add_circuit_connection(RED, f"acc_o_{i}", f"acc_o_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"gate_{i}", f"acc_o_{i}", side_1="output", side_2="input")

    acc_s = ArithmeticCombinator(id=f"acc_s_{i}", position=(gx + 4.5, gy + 1.0), first_operand="signal-B", operation="+", second_operand="signal-S", output_signal="signal-B")
    bp.entities.append(acc_s)
    bp.add_circuit_connection(RED, f"acc_s_{i}", f"acc_s_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"gate_{i}", f"acc_s_{i}", side_1="output", side_2="input")

# ---- power: generous lattice, same fast approach as Reshenie 15 ----
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
with open("stage2_octave_isolated_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)

print(f"Entities: {len(bp.entities)}")
print(f"K={K}, N_TEST={N_TEST}, full sweep = {N_TEST*K} ticks (~{N_TEST*K/60:.0f}s)")
print(f"TEST_VALS={TEST_VALS}")
print(f"EXPECTED (o,s)={EXPECTED}")
print("Saved stage2_octave_isolated_test_blueprint.txt")
