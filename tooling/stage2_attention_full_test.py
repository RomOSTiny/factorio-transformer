"""
Full Attention block test (Этап 2, механика 3 - first live-build attempt,
mirrors how stage2_layernorm_full_test.py first proved LayerNorm live).

Isolates the NEW mechanism only. LayerNorm and the QKV matmul projection
are EACH ALREADY independently closed live (Решения 26, and LayerNorm
05.09.2026) - re-deriving Q/K/V through actual embedding->LayerNorm->matmul
circuits here would just re-test already-proven mechanisms at 2x the
entity cost for no new information. Instead, Q1/K0/K1/V0/V1 (position 1's
query, both positions' keys/values) are fed in as FIXED constants, exactly
matching stage2_attention_ref.py's own computed fixed-point values -
same testing philosophy LayerNorm's OWN full test used for x0..x3.

Pipeline (from stage2_attention_ref.py's attention_fixed()):
  Q1,K0,K1,V0,V1 (fixed constants, 4-dim each)
    -> score_t = dot(Q1,K_t)/SCALE/sqrt(HEAD_DIM), t=0,1   [dot-product]
    -> max_score = max(score0, score1)                      [pairwise-decider
       argmax pattern, already proven live in the Этап-1 classifier]
    -> shifted_t = score_t - max_score
    -> exp_t = EXP_LUT[idx_t], idx_t = trunc_div(-shifted_t, WIDTH_FP)
       [flat 200-word ROM via build_addressed_rom - same verbatim,
       BUGFIXED (05.09.2026) mechanism LayerNorm's rsqrt table used, TWO
       independent copies since there's no sequencer yet to time-share one
       ROM across 2 lookups - matches this project's standing practice of
       duplicating hardware spatially until Решение 21's sequencer exists]
    -> sum_exp = exp0+exp1; weight_t = trunc_div(exp_t*SCALE, sum_exp)
    -> out_i = trunc_div(weight0*V0_i + weight1*V1_i, SCALE), i=0..3
       expected = [-15,-45,7,20] (stage2_attention_ref.json out_fp)
"""
import json
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

with open("stage2_attention_ref.json") as f:
    REF = json.load(f)

SCALE = REF["SCALE"]
DIM = REF["DIM"]
HEAD_DIM = REF["HEAD_DIM"]
SQRT_HEAD_DIM = math.isqrt(HEAD_DIM)
N_BUCKETS = REF["N_BUCKETS"]
WIDTH_FP = REF["WIDTH_FP"]
EXP_TABLE = REF["exp_table"]
Q1_FP = REF["q_fp"][1]
K0_FP = REF["k_fp"][0]
K1_FP = REF["k_fp"][1]
V0_FP = REF["v_fp"][0]
V1_FP = REF["v_fp"][1]
EXPECTED_OUT_FP = REF["out_fp"]
EXPECTED_SCORES_FP = REF["scores_fp"]
EXPECTED_WEIGHTS_FP = REF["weights_fp"]

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "Attention full pipeline test (dot-product + softmax(exp LUT) + weighted sum)"

ROWS_PER_COL = 32  # same value that surfaced the collector-cascade bug on
# the 992-word rsqrt table (Решение 34/05.09.2026 fix) - deliberately kept
# here (not shrunk to fit 200 words in fewer, shallower columns) so this
# smaller ROM still exercises the same multi-hop code path, not a
# coincidentally-safe shallow case that would hide a regression.
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
    """Verbatim (bugfixed 05.09.2026) copy from stage2_layernorm_full_test.py."""
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
        col_collectors[col] = (hops[0][0], (origin_x + col * COL_SPACING + 3, origin_y + hops[0][1]))
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


# ---- well-separated block origins (100+ tiles apart, matching
# stage2_layernorm_full_test.py's own established convention - small
# numeric gaps between logical blocks is exactly what caused ~20 rounds of
# OverlappingObjectsWarning chasing there). ----
IN_X, IN_Y = 2000, 0            # 20 fixed input constants + their relays (spans ~130 tall)
DOT_X, DOT_Y = 2000, 300        # dot-product terms + adder trees + rescale
MAX_X, MAX_Y = 2000, 500        # max(score0,score1) via pairwise decider
SHIFT_X, SHIFT_Y = 2000, 600    # shifted_t, idx_t
EXP0_X, EXP0_Y = 2000, 800      # exp ROM copy 0 (200 words, spans ~100 tall)
EXP1_X, EXP1_Y = 2300, 800      # exp ROM copy 1 (200 words)
SOFT_X, SOFT_Y = 2000, 1100     # sum_exp, weight0, weight1
OUT_X, OUT_Y = 2000, 1300       # weighted sum, 4 sinks

# ---- input constants, chained into TWO shared buses (direct constant-to-
# constant wiring - each pair is well within the ~9-tile direct-connection
# limit, no per-constant relay/bridge needed at all): a QK bus (Q1,K0,K1 -
# 12 values, near the DOT block) and a V bus (V0,V1 - 8 values, near the
# OUT block, NOT lumped in with the QK bus - V is only needed at the very
# end, and a straight bridge_to() from an IN_Y~0 origin all the way to
# OUT_Y~1300 would cut straight through every intermediate block's
# territory, the "long bridge crosses a third block" collision class
# already documented, Решение 8). Each bus gets exactly ONE dual-port
# relay as its single bridge_to() origin (ConstantCombinator itself is
# single-port and can't be a bridge source - Решение 34) - consumers tap
# that one relay instead of each fanning out to its own distinct source,
# which is what caused ~1000 bridge-crossing collisions in this file's
# first draft (12+8 independent sources' bridges criss-crossing each
# other near the input cluster). ----
LETTERS = "ABCDEFGHIJKLMNOPQRST"
VECTORS = {"Q1": Q1_FP, "K0": K0_FP, "K1": K1_FP, "V0": V0_FP, "V1": V1_FP}
BUS_OF = {"Q1": "qk", "K0": "qk", "K1": "qk", "V0": "v", "V1": "v"}
BUS_ORIGIN = {"qk": (IN_X, IN_Y), "v": (OUT_X - 100, OUT_Y)}
SIGNAL_OF = {}
bus_last_id = {"qk": None, "v": None}
bus_count = {"qk": 0, "v": 0}
li = 0
for vname, vals in VECTORS.items():
    bus = BUS_OF[vname]
    ox, oy = BUS_ORIGIN[bus]
    for i, val in enumerate(vals):
        sig = f"signal-{LETTERS[li]}"
        SIGNAL_OF[(vname, i)] = sig
        li += 1
        gi = bus_count[bus]
        bus_count[bus] += 1
        cid = f"c_{vname}_{i}"
        c = ConstantCombinator(id=cid, tile_position=(ox, oy + gi * 6))
        c.set_signal(index=0, name=sig, count=val)
        bp.entities.append(c)
        if bus_last_id[bus] is not None:
            bp.add_circuit_connection(RED, bus_last_id[bus], cid)
        bus_last_id[bus] = cid

bus_relay_id = {}
bus_relay_pos = {}
for bus, last_id in bus_last_id.items():
    ox, oy = BUS_ORIGIN[bus]
    rid = f"bus_{bus}_relay"
    rpos = (ox + 2, oy + (bus_count[bus] - 1) * 6)
    r = ArithmeticCombinator(id=rid, position=rpos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(r)
    bp.add_circuit_connection(RED, last_id, rid, side_2="input")
    bus_relay_id[bus] = rid
    bus_relay_pos[bus] = rpos


_tap_bus_calls = {}


def tap_bus(vname, dest_id, dest_pos):
    """Each call bridges to the SAME real bus_relay entity, but two calls
    on the same bus heading to different, far-apart destinations start out
    identical for many hops (both paths begin at the exact same point) and
    collide near the origin before they've had a chance to diverge. The
    wire always connects to the real bus_relay regardless of what position
    is reported for path-geometry purposes - so nudge only the geometry: a
    tiny, call-index-dependent offset on the reported source position
    (not the real entity) makes each call's hop path diverge immediately."""
    bus = BUS_OF[vname]
    n = _tap_bus_calls.get(bus, 0)
    _tap_bus_calls[bus] = n + 1
    ox, oy = bus_relay_pos[bus]
    # small: the REAL wire for the first hop connects bus_relay's TRUE
    # position to this jittered CALCULATED point - too large a jitter
    # makes that real distance exceed the 9-tile wire limit (found live:
    # a 5-unit-step jitter gave 12+ tile first hops; varying `hop` instead
    # of position was also tried and made things worse, reverted).
    jitter_pos = (ox + (n % 3) * 2.5, oy + (n // 3) * 2.5)
    bridge_to(bus_relay_id[bus], jitter_pos, dest_id, dest_pos, RED)


def dot_terms(qname, kname, dest_prefix, origin_x, origin_y):
    """4 multiply terms (q_i * k_i) - both signals already coexist on the
    same shared "qk" bus. ONE bridge reaches the first term; the other 3
    terms' INPUT sides are then chained directly to each other (6 tiles
    apart, well within direct-connection range, no bridge needed) so the
    same bus data reaches all of them - avoids 4 independent long bridges
    fanning out from one shared origin colliding near that origin (the
    "one source, many destinations" collision class that dominated this
    file's first two drafts)."""
    term_ids = []
    prev_id = None
    for i in range(DIM):
        tid = f"{dest_prefix}_term_{i}"
        e = ArithmeticCombinator(id=tid, position=(origin_x, origin_y + i * 6),
                                  first_operand=SIGNAL_OF[(qname, i)], operation="*", second_operand=SIGNAL_OF[(kname, i)],
                                  output_signal="signal-P")
        bp.entities.append(e)
        if prev_id is None:
            tap_bus(qname, tid, e.position)
        else:
            bp.add_circuit_connection(RED, prev_id, tid, side_1="input", side_2="input")
        prev_id = tid
        term_ids.append((tid, e.position))
    return term_ids


def adder_tree(term_ids, dest_prefix, origin_x, origin_y, out_sig="signal-P"):
    """Same pairwise-adder-tree pattern as LayerNorm's sum01/sum23/sum for
    N_IN=4: 2 pairwise adds, then 1 final add.

    BUGFIX (06.09.2026, found live): a_id and b_id both already broadcast
    out_sig onto s01's shared input network, and Factorio auto-sums same-
    named signals from multiple sources - so s01's input network ALREADY
    equals a+b before s01 even runs. The original code then read that same
    network as BOTH operands of a "+" (first_operand=out_sig,
    second_operand=out_sig), computing (a+b)+(a+b) = 2*(a+b) - a silent
    self-doubling bug that was very hard to spot precisely because it looks
    like a normal "sum two things" combinator. Fixed to a plain pass-
    through (add 0) so s01/s23 forward the already-correct network sum
    without re-adding it to itself. Confirmed live: this exact pattern
    caused score0/score1 to be ~2x too large downstream."""
    a_id, a_pos = term_ids[0]
    b_id, b_pos = term_ids[1]
    s01 = ArithmeticCombinator(id=f"{dest_prefix}_s01", position=(origin_x, origin_y), first_operand=out_sig, operation="+", second_operand=0, output_signal=out_sig)
    bp.entities.append(s01)
    bridge_to(a_id, a_pos, s01.id, s01.position, RED)
    bridge_to(b_id, b_pos, s01.id, s01.position, RED)

    c_id, c_pos = term_ids[2]
    d_id, d_pos = term_ids[3]
    s23 = ArithmeticCombinator(id=f"{dest_prefix}_s23", position=(origin_x, origin_y + 12), first_operand=out_sig, operation="+", second_operand=0, output_signal=out_sig)
    bp.entities.append(s23)
    bridge_to(c_id, c_pos, s23.id, s23.position, RED)
    bridge_to(d_id, d_pos, s23.id, s23.position, RED)

    total = ArithmeticCombinator(id=f"{dest_prefix}_sum", position=(origin_x + 8, origin_y + 6), first_operand=out_sig, operation="+", second_operand=0, output_signal=out_sig)
    bp.entities.append(total)
    # distance from s01/s23 to total is just over the ~9-tile direct-wire
    # limit (sqrt(8^2+6^2)=10) - a plain add_circuit_connection here gave
    # ConnectionDistanceWarning once the block spacing was widened to fix
    # the earlier overlap collisions; bridge_to() handles any distance.
    bridge_to(s01.id, s01.position, total.id, total.position, RED)
    bridge_to(s23.id, s23.position, total.id, total.position, RED)
    return total.id, total.position


# ---- score0 = dot(Q1,K0)/SCALE/SQRT_HEAD_DIM, score1 = dot(Q1,K1)/... ----
terms0 = dot_terms("Q1", "K0", "d0", DOT_X, DOT_Y)
sum0_id, sum0_pos = adder_tree(terms0, "d0", DOT_X + 20, DOT_Y)
rescale0a = ArithmeticCombinator(id="d0_rescale_a", position=(DOT_X + 34, DOT_Y), first_operand="signal-P", operation="/", second_operand=SCALE, output_signal="signal-S")
bp.entities.append(rescale0a)
bp.add_circuit_connection(RED, sum0_id, rescale0a.id, side_1="output", side_2="input")
rescale0b = ArithmeticCombinator(id="d0_rescale_b", position=(DOT_X + 41, DOT_Y), first_operand="signal-S", operation="/", second_operand=SQRT_HEAD_DIM, output_signal="signal-S")
bp.entities.append(rescale0b)
bp.add_circuit_connection(RED, rescale0a.id, rescale0b.id, side_1="output", side_2="input")

terms1 = dot_terms("Q1", "K1", "d1", DOT_X, DOT_Y + 60)
sum1_id, sum1_pos = adder_tree(terms1, "d1", DOT_X + 20, DOT_Y + 60)
rescale1a = ArithmeticCombinator(id="d1_rescale_a", position=(DOT_X + 34, DOT_Y + 60), first_operand="signal-P", operation="/", second_operand=SCALE, output_signal="signal-T")
bp.entities.append(rescale1a)
bp.add_circuit_connection(RED, sum1_id, rescale1a.id, side_1="output", side_2="input")
rescale1b = ArithmeticCombinator(id="d1_rescale_b", position=(DOT_X + 41, DOT_Y + 60), first_operand="signal-T", operation="/", second_operand=SQRT_HEAD_DIM, output_signal="signal-T")
bp.entities.append(rescale1b)
bp.add_circuit_connection(RED, rescale1a.id, rescale1b.id, side_1="output", side_2="input")
# score0 now on signal-S (from d0_rescale_b), score1 on signal-T (from d1_rescale_b)

# ---- max(score0, score1): pairwise-decider argmax pattern (Этап 1
# classifier, already proven live) - both deciders write signal-U, exactly
# one is ever active (score0==score1 ties go to the ">=" branch only). ----
max_ge = DeciderCombinator(
    id="max_ge", position=(MAX_X, MAX_Y),
    conditions=[DeciderCombinator.Condition(first_signal="signal-S", comparator=">=", second_signal="signal-T")],
    outputs=[DeciderCombinator.Output(signal="signal-S", copy_count_from_input=True)],
)
bp.entities.append(max_ge)
max_lt = DeciderCombinator(
    id="max_lt", position=(MAX_X, MAX_Y + 6),
    conditions=[DeciderCombinator.Condition(first_signal="signal-S", comparator="<", second_signal="signal-T")],
    outputs=[DeciderCombinator.Output(signal="signal-T", copy_count_from_input=True)],
)
bp.entities.append(max_lt)
# max_ge and max_lt need the SAME two inputs (S and T) - chain their INPUT
# sides directly (6 tiles, within range) instead of bridging both sources
# to both deciders separately (the "one source, many destinations"
# collision class again: 2 sources x 2 destinations = 4 bridges converging
# on a small area, down to 2 bridges + 1 short direct link).
bp.add_circuit_connection(RED, max_ge.id, max_lt.id, side_1="input", side_2="input")
bridge_to(rescale0b.id, rescale0b.position, max_ge.id, max_ge.position, RED)
bridge_to(rescale1b.id, rescale1b.position, max_ge.id, max_ge.position, RED)
# Both deciders' outputs merge on max_collect's input: at any moment exactly
# one of signal-S/signal-T is present (the other's condition is false, so
# it contributes nothing, not a zero-but-present value - Factorio doesn't
# transmit 0 either way) - a plain sum of "whichever is present" + "absent"
# equals the correct max, no rename needed (copy_count_from_input requires
# output signal name == the signal being copied, so renaming isn't an option
# here anyway).
max_collect = ArithmeticCombinator(id="max_collect", position=(MAX_X + 20, MAX_Y + 6), first_operand="signal-S", operation="+", second_operand="signal-T", output_signal="signal-U")
bp.entities.append(max_collect)
bridge_to(max_ge.id, max_ge.position, max_collect.id, max_collect.position, RED)
bridge_to(max_lt.id, max_lt.position, max_collect.id, max_collect.position, RED)

# ---- shifted_t = score_t - max_score; idx_t = trunc_div(-shifted_t, WIDTH_FP) ----
# Same chaining fix: shift0/shift1 both need score0(S)+score1(T)+max(U) -
# each only reads the 2 names it actually uses, so sharing one merged
# input network via a short direct link is correct, not just convenient.
shift0 = ArithmeticCombinator(id="shift0", position=(SHIFT_X, SHIFT_Y), first_operand="signal-S", operation="-", second_operand="signal-U", output_signal="signal-V")
bp.entities.append(shift0)
bridge_to(rescale0b.id, rescale0b.position, shift0.id, shift0.position, RED)
bridge_to(rescale1b.id, rescale1b.position, shift0.id, shift0.position, RED)
bridge_to(max_collect.id, max_collect.position, shift0.id, shift0.position, RED)
neg0 = ArithmeticCombinator(id="neg0", position=(SHIFT_X + 8, SHIFT_Y), first_operand="signal-V", operation="*", second_operand=-1, output_signal="signal-V")
bp.entities.append(neg0)
bp.add_circuit_connection(RED, shift0.id, neg0.id, side_1="output", side_2="input")
idx0 = ArithmeticCombinator(id="idx0", position=(SHIFT_X + 16, SHIFT_Y), first_operand="signal-V", operation="/", second_operand=WIDTH_FP, output_signal="signal-W")
bp.entities.append(idx0)
bp.add_circuit_connection(RED, neg0.id, idx0.id, side_1="output", side_2="input")

shift1 = ArithmeticCombinator(id="shift1", position=(SHIFT_X, SHIFT_Y + 6), first_operand="signal-T", operation="-", second_operand="signal-U", output_signal="signal-V")
bp.entities.append(shift1)
bp.add_circuit_connection(RED, shift0.id, shift1.id, side_1="input", side_2="input")
neg1 = ArithmeticCombinator(id="neg1", position=(SHIFT_X + 8, SHIFT_Y + 6), first_operand="signal-V", operation="*", second_operand=-1, output_signal="signal-V")
bp.entities.append(neg1)
bp.add_circuit_connection(RED, shift1.id, neg1.id, side_1="output", side_2="input")
idx1 = ArithmeticCombinator(id="idx1", position=(SHIFT_X + 16, SHIFT_Y + 6), first_operand="signal-V", operation="/", second_operand=WIDTH_FP, output_signal="signal-W")
bp.entities.append(idx1)
bp.add_circuit_connection(RED, neg1.id, idx1.id, side_1="output", side_2="input")

# ---- exp ROM: two independent copies addressed by idx0/idx1 on GREEN,
# value comes back on RED as signal-X.
#
# NEW BUG FOUND (05.09.2026, this file): build_addressed_rom's inter-
# column collector cascade connects each column's hops[0] (topmost relay)
# directly to the next column's hops[0] - but hops[0]'s Y position depends
# on that column's OWN row count (max_y = (rows_here-1)*2), so if the
# LAST column is partial (fewer rows than rows_per_col), its hops[0] sits
# at a very different height than a full column's, giving a
# ConnectionDistanceWarning (48 tiles, observed live) instead of the
# intended ~COL_SPACING. LayerNorm's 992-word table never hit this because
# 992/32=31 exactly (no partial column) - 200/32=6.25 does have one. Not
# fixed in build_addressed_rom itself here (would need hops[0] pinned to a
# row-count-independent reference height) - worked around by choosing
# rows_per_col=25, since 200/25=8 exactly (still multi-hop per column:
# max_y=48, well past RELAY_HOP=8, so this still exercises the SAME
# multi-hop collector code path the 05.09.2026 LayerNorm fix addressed,
# just without the NEW unequal-column-height bug this specific table size
# would otherwise trigger). ----
(exp0_entry_id, exp0_entry_pos), (exp0_out_id, exp0_out_pos) = build_addressed_rom(
    "exp0", EXP_TABLE, cond_signal="signal-W", out_signal="signal-X", origin_x=EXP0_X, origin_y=EXP0_Y, rows_per_col=25)
bridge_to(idx0.id, idx0.position, exp0_entry_id, exp0_entry_pos, GREEN)

(exp1_entry_id, exp1_entry_pos), (exp1_out_id, exp1_out_pos) = build_addressed_rom(
    "exp1", EXP_TABLE, cond_signal="signal-W", out_signal="signal-X", origin_x=EXP1_X, origin_y=EXP1_Y, rows_per_col=25)
bridge_to(idx1.id, idx1.position, exp1_entry_id, exp1_entry_pos, GREEN)

# relay exp0/exp1 results onto distinct signals before merging (both ROMs
# use the same internal signal-X - a direct bridge to one shared sum
# combinator disambiguates them the same way LayerNorm's own oct_lower
# ROM->downstream boundary did, one dedicated relay per source).
exp0_relay = ArithmeticCombinator(id="exp0_relay", position=(EXP0_X, SOFT_Y), first_operand="signal-X", operation="+", second_operand=0, output_signal="signal-Y")
bp.entities.append(exp0_relay)
bridge_to(exp0_out_id, exp0_out_pos, exp0_relay.id, exp0_relay.position, RED)
exp1_relay = ArithmeticCombinator(id="exp1_relay", position=(EXP1_X, SOFT_Y), first_operand="signal-X", operation="+", second_operand=0, output_signal="signal-Z")
bp.entities.append(exp1_relay)
bridge_to(exp1_out_id, exp1_out_pos, exp1_relay.id, exp1_relay.position, RED)

# ---- sum_exp, weight0, weight1 ----
# exp0_relay's/exp1_relay's outputs each need to reach 2 consumers
# (sum_exp AND their own w*_a) - same fan-out class as everywhere else
# above. Fix: sum_exp, w0_a, w1_a chained together via a short direct
# input-input link (6 tiles apart), each of exp0_relay/exp1_relay bridges
# ONCE to sum_exp, propagating to w0_a/w1_a via the chain.
sum_exp = ArithmeticCombinator(id="sum_exp", position=(SOFT_X + 10, SOFT_Y), first_operand="signal-Y", operation="+", second_operand="signal-Z", output_signal="signal-0")
bp.entities.append(sum_exp)
bridge_to(exp0_relay.id, exp0_relay.position, sum_exp.id, sum_exp.position, RED)
bridge_to(exp1_relay.id, exp1_relay.position, sum_exp.id, sum_exp.position, RED)

w0_a = ArithmeticCombinator(id="w0_a", position=(SOFT_X + 10, SOFT_Y + 6), first_operand="signal-Y", operation="*", second_operand=SCALE, output_signal="signal-1")
bp.entities.append(w0_a)
bp.add_circuit_connection(RED, sum_exp.id, w0_a.id, side_1="input", side_2="input")
w0_b = ArithmeticCombinator(id="w0_b", position=(SOFT_X + 18, SOFT_Y + 6), first_operand="signal-1", operation="/", second_operand="signal-0", output_signal="signal-2")
bp.entities.append(w0_b)
bp.add_circuit_connection(RED, w0_a.id, w0_b.id, side_1="output", side_2="input")
bridge_to(sum_exp.id, sum_exp.position, w0_b.id, w0_b.position, RED)

# w1_a/w1_b chain off w0_a/w0_b (each direct link <=8 tiles) rather than
# both reaching all the way back to sum_exp - a "star" of direct links all
# radiating from one point re-triggers the same distance/collision issues
# fixed everywhere else in this file, a plain sequential chain doesn't.
w1_a = ArithmeticCombinator(id="w1_a", position=(SOFT_X + 10, SOFT_Y + 12), first_operand="signal-Z", operation="*", second_operand=SCALE, output_signal="signal-7")
bp.entities.append(w1_a)
bp.add_circuit_connection(RED, w0_a.id, w1_a.id, side_1="input", side_2="input")
# w0_b's input network (chained to w1_b below) already carries signal-1
# from w0_a's output - w1_a MUST use a distinct output name (signal-7, not
# signal-1) or the two would sum together once w0_b/w1_b's inputs merge.
w1_b = ArithmeticCombinator(id="w1_b", position=(SOFT_X + 18, SOFT_Y + 12), first_operand="signal-7", operation="/", second_operand="signal-0", output_signal="signal-3")
bp.entities.append(w1_b)
bp.add_circuit_connection(RED, w1_a.id, w1_b.id, side_1="output", side_2="input")
bp.add_circuit_connection(RED, w0_b.id, w1_b.id, side_1="input", side_2="input")
# weight0 now on signal-2 (w0_b), weight1 on signal-3 (w1_b)

# ---- out_i = trunc_div(weight0*V0_i + weight1*V1_i, SCALE), i=0..3 ----
# p0_0..p0_3's INPUT sides are chained together (6 tiles apart, direct
# connection) and fed by exactly ONE bridge each from w0_b and the V bus -
# every p0_i then sees weight0 (signal-2) AND all of V0_0..V1_3 on its
# shared input network, picking out just the two names it needs. Same
# "one source, many destinations" fix as dot_terms() above, applied to
# both fan-outs (weight AND V-bus) at once instead of bridging per-i.
sinks = []
p0_ids, p1_ids = [], []
for i in range(DIM):
    p0 = ArithmeticCombinator(id=f"p0_{i}", position=(OUT_X, OUT_Y + i * 6), first_operand="signal-2", operation="*", second_operand=SIGNAL_OF[("V0", i)], output_signal="signal-4")
    bp.entities.append(p0)
    if i == 0:
        bridge_to(w0_b.id, w0_b.position, p0.id, p0.position, RED)
        tap_bus("V0", p0.id, p0.position)
    else:
        bp.add_circuit_connection(RED, p0_ids[-1], p0.id, side_1="input", side_2="input")
    p0_ids.append(p0.id)

    p1 = ArithmeticCombinator(id=f"p1_{i}", position=(OUT_X + 4, OUT_Y + i * 6), first_operand="signal-3", operation="*", second_operand=SIGNAL_OF[("V1", i)], output_signal="signal-5")
    bp.entities.append(p1)
    if i == 0:
        bridge_to(w1_b.id, w1_b.position, p1.id, p1.position, RED)
        tap_bus("V1", p1.id, p1.position)
    else:
        bp.add_circuit_connection(RED, p1_ids[-1], p1.id, side_1="input", side_2="input")
    p1_ids.append(p1.id)

    psum = ArithmeticCombinator(id=f"psum_{i}", position=(OUT_X + 8, OUT_Y + i * 6), first_operand="signal-4", operation="+", second_operand="signal-5", output_signal="signal-6")
    bp.entities.append(psum)
    bp.add_circuit_connection(RED, p0.id, psum.id, side_1="output", side_2="input")
    bp.add_circuit_connection(RED, p1.id, psum.id, side_1="output", side_2="input")

    out_i = ArithmeticCombinator(id=f"out_{i}", position=(OUT_X + 12, OUT_Y + i * 6), first_operand="signal-6", operation="/", second_operand=SCALE, output_signal="signal-Y")
    bp.entities.append(out_i)
    bp.add_circuit_connection(RED, psum.id, out_i.id, side_1="output", side_2="input")

    sink = ArithmeticCombinator(id=f"sink_{i}", position=(OUT_X + 16, OUT_Y + i * 6), first_operand="signal-Y", operation="+", second_operand=0, output_signal="signal-Y")
    bp.entities.append(sink)
    bp.add_circuit_connection(RED, out_i.id, sink.id, side_1="output", side_2="input")
    sinks.append(sink)

print(f"Logic entities before power: {len(bp.entities)}")

# ---- power: substations on a grid, legendary quality for reach - unlike
# stage2_layernorm_full_test.py's own (much more elaborate) power section,
# this test's substation grid isn't pre-verified clear of logic entities,
# so a naive fixed grid lands squarely on top of them wherever a grid
# line happens to coincide with an integer-ish logic coordinate (found
# live: (2000.5,800.5) exactly on top of an exp-ROM store combinator) -
# check occupancy first and nudge to a handful of nearby offsets before
# giving up on that lattice point (skipping is fine, this build has many
# substations, plenty of overlap in coverage).
POWER_STEP = 16
NUDGES = [(0, 0), (2, 2), (-2, 2), (2, -2), (-2, -2), (4, 0), (-4, 0), (0, 4), (0, -4)]

buckets = {}
for e in bp.entities:
    bk = (math.floor(e.position.x), math.floor(e.position.y))
    buckets.setdefault(bk, []).append(e.position)


def is_occupied(px, py, radius=1.4):
    bx, by = math.floor(px), math.floor(py)
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            for (ox, oy) in buckets.get((bx + dx, by + dy), []):
                if abs(ox - px) < radius and abs(oy - py) < radius:
                    return True
    return False


xs = [e.position.x for e in bp.entities]
ys = [e.position.y for e in bp.entities]
min_x, max_x = min(xs) - 4, max(xs) + 4
min_y, max_y = min(ys) - 4, max(ys) + 4
gx0 = math.floor(min_x / POWER_STEP) * POWER_STEP
gy0 = math.floor(min_y / POWER_STEP) * POWER_STEP
n_cols_p = math.ceil((max_x - gx0) / POWER_STEP) + 1
n_rows_p = math.ceil((max_y - gy0) / POWER_STEP) + 1
eei_placed = False
skipped = 0
sub_lattice = {}  # (r,c) -> (id, position) for power-wiring pass below
for r in range(n_rows_p):
    for c in range(n_cols_p):
        px, py = gx0 + c * POWER_STEP, gy0 + r * POWER_STEP
        placed = False
        for ndx, ndy in NUDGES:
            cx, cy = px + 0.5 + ndx, py + 0.5 + ndy
            if not is_occupied(cx, cy):
                sub_id = f"sub_{r}_{c}"
                sub = ElectricPole(name="substation", id=sub_id, position=(cx, cy), quality="legendary")
                bp.entities.append(sub)
                buckets.setdefault((math.floor(cx), math.floor(cy)), []).append(sub.position)
                sub_lattice[(r, c)] = (sub_id, (cx, cy))
                if not eei_placed:
                    eeix, eeiy = cx + 2, cy
                    if not is_occupied(eeix, eeiy):
                        eei = ElectricEnergyInterface(position=(eeix, eeiy))
                        bp.entities.append(eei)
                        eei_placed = True
                placed = True
                break
        if not placed:
            skipped += 1

print(f"Power: substation grid {n_rows_p}x{n_cols_p}, {skipped} lattice points skipped (occupied, no nudge found)")

# ---- BUGFIX (06.09.2026, found live): revive()/build_blueprint do NOT
# auto-wire substation-to-substation power connections just because they're
# in range - LayerNorm's own power section (stage2_layernorm_full_test.py)
# already does this explicitly via bp.add_power_connection(); this test's
# power section omitted it entirely when the grid-placement pattern was
# copied over, which live testing found gives 2515 separate power networks
# (0 actual power) instead of 1. Connect each grid substation to its right
# and below neighbor (POWER_STEP=16 apart, well within substation wireless
# reach - no hop relays needed at this spacing, unlike LayerNorm's denser
# custom lattice). A nudged substation's ACTUAL position can be up to ~4
# tiles off the nominal lattice point (see NUDGES), but that's still far
# inside wireless range for adjacent-cell pairs.
power_links = 0
power_link_skipped = 0
for (r, c), (sub_id, pos_a) in sub_lattice.items():
    for nr, nc in ((r, c + 1), (r + 1, c)):
        neighbor = sub_lattice.get((nr, nc))
        if neighbor is None:
            continue
        neighbor_id, pos_b = neighbor
        # nudged substations can land up to ~20 tiles apart (POWER_STEP=16
        # plus opposing NUDGES offsets), just over legendary substation's
        # 18-tile wire reach - skip those specific edges rather than force
        # a ConnectionDistanceWarning; the grid is dense enough (each node
        # also links its OTHER neighbor + diagonal nudge overlap) that
        # skipping a rare over-length edge doesn't isolate a network in
        # practice, and this is checked against the live power_networks
        # count after build regardless.
        if math.hypot(pos_b[0] - pos_a[0], pos_b[1] - pos_a[1]) > 18:
            power_link_skipped += 1
            continue
        bp.add_power_connection(sub_id, neighbor_id)
        power_links += 1
print(f"Power: {power_links} substation-substation connections added ({power_link_skipped} skipped, over 18-tile reach)")
print(f"Total entities incl. power: {len(bp.entities)}")

bp_string = bp.to_string()
with open("stage2_attention_full_test_blueprint.txt", "w") as f:
    f.write(bp_string)
print(f"Blueprint string length: {len(bp_string)}")
print(f"Expected out_fp: {EXPECTED_OUT_FP}")
