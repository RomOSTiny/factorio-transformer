"""
Parametrized Attention block (Этап 2, механика 4 - Sequencer).

Copy of stage2_attention_full_test.py (CLOSED live 08.09.2026) with the
CORE pipeline verbatim, plus the parametrization needed to drop it into
the forward-pass DAG:
  - position sweep: Q muxed by pos from a 2-slot buffer (counter #1);
  - growing-window mask: for pos 0 key 1 doesn't exist yet -> subtract
    BIGMASK from the d1 dot-product SUM (pre-rescale) so exp(score1-max)
    underflows and weight1 -> 0 (validated numerically in
    stage2_attention_param_ref.py). Counter #2 drives the mask decider.
    The mask is FOLDED INTO d1's adder-tree final combinator - mask_gen
    sits hard against d1_sum and feeds it a direct <9-tile GREEN wire, so
    there is NO bridge crossing the score-descent corridor (that crossing
    was the source of the mask<->score cross-contamination, 09.09.2026);
  - output latches: per-position gated latch -> ATTN_OUT buffer (counter #3).

ROUTING DISCIPLINE (09.09.2026 rework - the previous draft inherited the
x4 dot-product bug and then, after a partial _nudge_clear fix, still had
d1's bus tap deliver nothing + mask/score merges in the crowded
DOT/MAX/SHIFT wedge):
  - bridge() is a PATH FOLLOWER: each hop is measured from the previous
    (possibly nudged) relay, so an obstacle nudge bends the path without
    ever stretching the gap to a chain neighbour past the ~9-tile wire
    limit. _nudge_clear's perpendicular step is capped at 4 tiles.
  - tap_bus() routes every consumer down its OWN far-left vertical lane
    (unique x per call, well clear of every logic column), so two taps on
    one bus never run near-parallel and never merge on revive.
  - score0/score1 merge onto ONE relay via a single clean vertical
    corridor, then ONE bridge into MAX; SHIFT is fed by ONE bridge from a
    local shift_feed relay. No diagonal bridge fans through the wedge.
"""
import json
import math
import warnings

_caught_warnings = []
_orig_showwarning = warnings.showwarning
def _showwarning(message, *args, **kwargs):
    _caught_warnings.append(str(message))
warnings.showwarning = _showwarning

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

with open("stage2_attention_ref.json") as f:
    REF = json.load(f)
with open("stage2_sequencer_ref.json") as f:
    SEQ = json.load(f)
with open("stage2_attention_param_ref.json") as f:
    PREF = json.load(f)   # masking-approach numeric ref (validated both positions)

SCALE = REF["SCALE"]
DIM = REF["DIM"]
HEAD_DIM = REF["HEAD_DIM"]
SQRT_HEAD_DIM = math.isqrt(HEAD_DIM)
N_BUCKETS = REF["N_BUCKETS"]
WIDTH_FP = REF["WIDTH_FP"]
EXP_TABLE = REF["exp_table"]

Q_FP_ALL = SEQ["q_fp"]          # [[...],[...]]  q per position
K_FP_ALL = SEQ["k_fp"]          # k for positions 0 and 1
V_FP_ALL = SEQ["v_fp"]
T = len(Q_FP_ALL)              # 2
ATTN_OUT_EXPECTED = SEQ["attn_out_fp"]   # [[2,-6,4,38], [-15,-45,7,20]]
BIGMASK = PREF["BIGMASK"]      # 10000
K_ATT = 1000                   # ticks per position, >> core settle depth
OFFSET_ATT = 0                 # isolated test: sweep from revival (no upstream)
PULSE = K_ATT * 7 // 10        # latch out_i this deep into each position's window
CLK_SIG, SH_SIG, POS_SIG, TMOD_SIG = "signal-red", "signal-green", "signal-8", "signal-9"
MASK_SIG = "signal-cyan"
ABUF_SIG = "signal-grey"       # every attn-out buffer cell holds its value here

K0_FP, K1_FP = K_FP_ALL[0], K_FP_ALL[1]
V0_FP, V1_FP = V_FP_ALL[0], V_FP_ALL[1]
Q1_FP = Q_FP_ALL[1]
EXPECTED_OUT_FP = ATTN_OUT_EXPECTED[1]
EXPECTED_SCORES_FP = REF["scores_fp"]
EXPECTED_WEIGHTS_FP = REF["weights_fp"]

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "Attention parametrized (position sweep, growing-window mask, live buffers)"

ROWS_PER_COL = 32
COL_SPACING = 4
RELAY_HOP = 7   # a touch of slack under the ~9-tile wire limit so a nudged
# relay (perp step <=4) still connects to its chain neighbours: sqrt(7^2+4^2)=8.06.
_bridge_ctr = 0


def _occupied_points():
    pts = []
    for e in bp.entities:
        p = e.position
        pts.append((p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1]))
    return pts


def _nudge_clear(pos, occ, path_dir, rx=1.4, ry=2.5, max_off=4.0):
    """If pos collides with an occupied point, step PERPENDICULAR to the
    path until clear. Combinators are 1x2 so the exclusion box is
    anisotropic. Capped at max_off tiles: a nudged relay must never drift
    far enough off-line to break the <=9-tile wire to its chain
    neighbours. If nothing clear within the cap, keep it on-line (chain
    integrity beats overlap avoidance - and a cap hit means the block
    layout is too tight, which the gen-time gates below will flag)."""
    def free(x, y):
        return all(abs(ox - x) >= rx or abs(oy - y) >= ry for ox, oy in occ)
    x, y = pos
    if free(x, y):
        return pos
    dx, dy = path_dir
    n = math.hypot(dx, dy) or 1.0
    px, py = -dy / n, dx / n
    step = 0.5
    while step <= max_off + 1e-9:
        for s in (1, -1):
            nx, ny = x + px * step * s, y + py * step * s
            if free(nx, ny):
                return (nx, ny)
        step += 0.5
    return pos


def bridge(from_id, from_pos, to_pos, color, hop=RELAY_HOP):
    """Path-following relay chain. Each hop steps `hop` tiles from the
    PREVIOUS relay's ACTUAL position toward to_pos, then nudges clear of
    obstacles - so nudges bend the route, they never stretch a link.
    Terminates with a relay at (near) to_pos."""
    global _bridge_ctr
    tx, ty = to_pos
    if math.hypot(tx - from_pos[0], ty - from_pos[1]) < 1e-9:
        return from_id, from_pos, 0
    occ = _occupied_points()
    prev_id, prev_pos = from_id, from_pos
    n_hops = 0
    while True:
        px, py = prev_pos
        rem = math.hypot(tx - px, ty - py)
        last = rem <= hop * 1.25
        if last:
            nom = (tx, ty)
        else:
            nom = (px + (tx - px) / rem * hop, py + (ty - py) / rem * hop)
        pos = _nudge_clear(nom, occ, (tx - px, ty - py))
        _bridge_ctr += 1
        bid = f"gbridge_{_bridge_ctr}"
        bp.entities.append(ArithmeticCombinator(id=bid, position=pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
        occ.append(pos)
        bp.add_circuit_connection(color, prev_id, bid, side_1="output", side_2="input")
        prev_id, prev_pos = bid, pos
        n_hops += 1
        if last or n_hops > 600:
            break
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


def route_L(from_id, from_pos, to_id, to_pos, color, lane_x, approach=-4):
    """L/Z-shaped bridge: out to lane_x, down/up that lane to just short of
    to_pos's row, along to to_pos's column, then a short direct wire in.
    Use when a straight bridge would fan through a congested region."""
    fx, fy = from_pos
    tx, ty = to_pos
    ly = ty + approach
    a, ap, _ = bridge(from_id, from_pos, (lane_x, fy), color)
    b, bpp, _ = bridge(a, ap, (lane_x, ly), color)
    d, dp, _ = bridge(b, bpp, (tx, ly), color)
    bridge_to(d, dp, to_id, to_pos, color)


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


# ---- well-separated block origins. Vertical spacing widened from the
# full-test values (MAX 500->520, SHIFT 600->660, ...) to give the
# inter-block bridge corridors room. ----
IN_X, IN_Y = 2000, 0            # 20 fixed input constants + Q-mux (Q-mux stuff at x 1974..1997)
DOT_X, DOT_Y = 2000, 300        # dot-product terms + adder trees + rescale + mask
MAX_X, MAX_Y = 2000, 520        # max(score0,score1)
SHIFT_X, SHIFT_Y = 2000, 660    # shifted_t, idx_t
EXP0_X, EXP0_Y = 2000, 860      # exp ROM copy 0 (200 words)
EXP1_X, EXP1_Y = 2300, 860      # exp ROM copy 1
SOFT_X, SOFT_Y = 2000, 1180     # sum_exp, weight0, weight1
OUT_X, OUT_Y = 2000, 1400       # weighted sum + output latches

# ---- input constants -> two shared buses (qk near DOT, v near OUT). ----
LETTERS = "ABCDEFGHIJKLMNOPQRST"
VECTORS = {"Q1": [0] * DIM, "K0": K0_FP, "K1": K1_FP, "V0": V0_FP, "V1": V1_FP}
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

# ============================================================================
# PARAMETRIZED INPUT: position sweep (counter #1) + Q-buffer + per-element mux.
# ============================================================================
QCTL_X = IN_X - 26              # 1974
q_tctr = ArithmeticCombinator(id="q_tctr", position=(QCTL_X + 0.5, IN_Y - 12.0), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
bp.entities.append(q_tctr)
bp.add_circuit_connection(RED, "q_tctr", "q_tctr", side_1="output", side_2="input")
q_sh = ArithmeticCombinator(id="q_sh", position=(QCTL_X + 3.5, IN_Y - 12.0), first_operand=CLK_SIG, operation="-", second_operand=OFFSET_ATT, output_signal=SH_SIG)
bp.entities.append(q_sh)
bp.add_circuit_connection(RED, "q_tctr", "q_sh", side_1="output", side_2="input")
q_pos = ArithmeticCombinator(id="q_pos", position=(QCTL_X + 0.5, IN_Y - 9.0), first_operand=SH_SIG, operation="/", second_operand=K_ATT, output_signal=POS_SIG)
bp.entities.append(q_pos)
bp.add_circuit_connection(RED, "q_sh", "q_pos", side_1="output", side_2="input")

# pos-distribution GREEN spine, one relay per Q element row (y = i*6)
POSDIST_X, QBUF0_X, QMUX0_X, QSEL_X = IN_X - 14, IN_X - 12, IN_X - 7.0, IN_X - 3.0
prev_pd = None
for i in range(DIM):
    pd = f"q_posdist_{i}"
    bp.entities.append(ArithmeticCombinator(id=pd, position=(POSDIST_X, IN_Y + i * 6), first_operand=POS_SIG, operation="+", second_operand=0, output_signal=POS_SIG))
    if prev_pd is None:
        bridge_to("q_pos", (QCTL_X + 0.5, IN_Y - 9.0), pd, (POSDIST_X, IN_Y), GREEN)
    else:
        bp.add_circuit_connection(GREEN, prev_pd, pd, side_1="output", side_2="input")
    prev_pd = pd

for i in range(DIM):
    sig = f"signal-{LETTERS[i]}"      # signal-A..D
    gy = IN_Y + i * 6
    for p in range(T):
        xb = ConstantCombinator(id=f"qbuf_{p}_{i}", tile_position=(int(QBUF0_X) + p * 2, int(gy)))
        xb.set_signal(index=0, name=sig, count=Q_FP_ALL[p][i])
        bp.entities.append(xb)
        mux = DeciderCombinator(
            id=f"qmux_{p}_{i}", position=(QMUX0_X + p * 1.5, gy),
            conditions=[DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=p)],
            outputs=[DeciderCombinator.Output(signal=sig, copy_count_from_input=True)],
        )
        bp.entities.append(mux)
        bp.add_circuit_connection(RED, f"qbuf_{p}_{i}", f"qmux_{p}_{i}", side_2="input")
        bp.add_circuit_connection(GREEN, f"q_posdist_{i}", f"qmux_{p}_{i}", side_1="output", side_2="input")
    qsel = ArithmeticCombinator(id=f"qsel_{i}", position=(QSEL_X, gy), first_operand=sig, operation="+", second_operand=0, output_signal=sig)
    bp.entities.append(qsel)
    for p in range(T):
        bp.add_circuit_connection(RED, f"qmux_{p}_{i}", f"qsel_{i}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"qsel_{i}", f"c_Q1_{i}", side_1="output")


_tap_bus_calls = {}
_bus_fan_last = {}


def tap_bus(vname, dest_id, dest_pos):
    """Route each consumer's tap down its OWN far-left vertical lane, well
    clear of every logic column, then along above the destination column
    and a short drop in.

    THE x4 BUG (09.09.2026): two taps on one bus otherwise start at the
    exact same point and run near-parallel down the x~2000 line for 250+
    tiles before diverging - their relays overlap and revive() merges them
    into a summation node, doubling both dot-product operands (product x4).
    A dedicated lane per call keeps the two paths physically apart the
    whole way. Fans are chained (not star-wired to bus_relay) so spacing
    them out never breaks the fan->source wire."""
    global _tap_bus_calls
    bus = BUS_OF[vname]
    n = _tap_bus_calls.get(bus, 0)
    _tap_bus_calls[bus] = n + 1
    ox, oy = bus_relay_pos[bus]
    fan = f"bus_{bus}_fan_{n}"
    fan_pos = (ox + 5 + n * 4, oy + 4 + n * 6)
    bp.entities.append(ArithmeticCombinator(id=fan, position=fan_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
    src = _bus_fan_last.get(bus, bus_relay_id[bus])
    bp.add_circuit_connection(RED, src, fan, side_1="output", side_2="input")
    _bus_fan_last[bus] = fan
    lane_x = min(dest_pos[0], ox) - 40 - n * 12       # unique, far left of all logic
    entry_y = dest_pos[1] - 6 - n * 4                  # approach column from above; staggered
    m1, m1p, _ = bridge(fan, fan_pos, (lane_x, fan_pos[1]), RED)
    m2, m2p, _ = bridge(m1, m1p, (lane_x, entry_y), RED)
    m3, m3p, _ = bridge(m2, m2p, (dest_pos[0], entry_y), RED)
    bridge_to(m3, m3p, dest_id, dest_pos, RED)


def dot_terms(qname, kname, dest_prefix, origin_x, origin_y):
    """4 multiply terms (q_i * k_i) - both signals coexist on the shared
    qk bus. ONE tap reaches term 0; terms 1..3 chain their INPUT sides
    directly (6 tiles apart)."""
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


def adder_tree(term_ids, dest_prefix, origin_x, origin_y, out_sig="signal-P", sub_sig=None, sub_src_id=None):
    """Pairwise adder tree (2 pairwise adds, 1 final add). s01/s23 are
    plain pass-throughs (add 0): a_id and b_id both broadcast out_sig onto
    the shared input net and Factorio auto-sums same-named signals, so the
    net ALREADY equals a+b before s01 runs (re-adding it to itself was the
    06.09.2026 self-doubling bug).

    If sub_sig is given, the final `total` computes (sum) - sub_sig
    instead of (sum) + 0, and sub_src_id is wired DIRECTLY onto total's
    GREEN input (it must be placed within ~9 tiles). This folds the
    growing-window mask into d1's adder tree with no crossing bridge."""
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

    if sub_sig is None:
        total = ArithmeticCombinator(id=f"{dest_prefix}_sum", position=(origin_x + 8, origin_y + 6), first_operand=out_sig, operation="+", second_operand=0, output_signal=out_sig)
    else:
        total = ArithmeticCombinator(id=f"{dest_prefix}_sum", position=(origin_x + 8, origin_y + 6), first_operand=out_sig, operation="-", second_operand=sub_sig, output_signal=out_sig)
    bp.entities.append(total)
    bridge_to(s01.id, s01.position, total.id, total.position, RED)
    bridge_to(s23.id, s23.position, total.id, total.position, RED)
    if sub_src_id is not None:
        bp.add_circuit_connection(GREEN, sub_src_id, total.id, side_1="output", side_2="input")
    return total.id, total.position


# ---- score0 = dot(Q1,K0)/SCALE/SQRT_HEAD_DIM ----
terms0 = dot_terms("Q1", "K0", "d0", DOT_X, DOT_Y)
sum0_id, sum0_pos = adder_tree(terms0, "d0", DOT_X + 20, DOT_Y)
rescale0a = ArithmeticCombinator(id="d0_rescale_a", position=(DOT_X + 34, DOT_Y), first_operand="signal-P", operation="/", second_operand=SCALE, output_signal="signal-S")
bp.entities.append(rescale0a)
bp.add_circuit_connection(RED, sum0_id, rescale0a.id, side_1="output", side_2="input")
rescale0b = ArithmeticCombinator(id="d0_rescale_b", position=(DOT_X + 41, DOT_Y), first_operand="signal-S", operation="/", second_operand=SQRT_HEAD_DIM, output_signal="signal-S")
bp.entities.append(rescale0b)
bp.add_circuit_connection(RED, rescale0a.id, rescale0b.id, side_1="output", side_2="input")

# ---- d1: mask counter (#2) placed hard against where d1_sum will sit, so
# mask_gen -> d1_sum is a direct <9-tile GREEN wire. NO bridge. ----
terms1 = dot_terms("Q1", "K1", "d1", DOT_X, DOT_Y + 60)
# d1 adder tree origin is (DOT_X+20, DOT_Y+60) -> d1_sum at (DOT_X+28, DOT_Y+66).
m_tctr = ArithmeticCombinator(id="m_tctr", position=(DOT_X + 31, DOT_Y + 53), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
bp.entities.append(m_tctr)
bp.add_circuit_connection(RED, "m_tctr", "m_tctr", side_1="output", side_2="input")
m_sh = ArithmeticCombinator(id="m_sh", position=(DOT_X + 31, DOT_Y + 56), first_operand=CLK_SIG, operation="-", second_operand=OFFSET_ATT, output_signal=SH_SIG)
bp.entities.append(m_sh)
bp.add_circuit_connection(RED, "m_tctr", "m_sh", side_1="output", side_2="input")
m_pos = ArithmeticCombinator(id="m_pos", position=(DOT_X + 28, DOT_Y + 56), first_operand=SH_SIG, operation="/", second_operand=K_ATT, output_signal=POS_SIG)
bp.entities.append(m_pos)
bp.add_circuit_connection(RED, "m_sh", "m_pos", side_1="output", side_2="input")
mask_gen = DeciderCombinator(
    id="mask_gen", position=(DOT_X + 28, DOT_Y + 61),
    conditions=[DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=0)],
    outputs=[DeciderCombinator.Output(signal=MASK_SIG, copy_count_from_input=False, constant=BIGMASK * SCALE * SQRT_HEAD_DIM)],
)
bp.entities.append(mask_gen)
bp.add_circuit_connection(RED, "m_pos", "mask_gen", side_1="output", side_2="input")

sum1_id, sum1_pos = adder_tree(terms1, "d1", DOT_X + 20, DOT_Y + 60, sub_sig=MASK_SIG, sub_src_id="mask_gen")
rescale1a = ArithmeticCombinator(id="d1_rescale_a", position=(DOT_X + 34, DOT_Y + 60), first_operand="signal-P", operation="/", second_operand=SCALE, output_signal="signal-T")
bp.entities.append(rescale1a)
bp.add_circuit_connection(RED, sum1_id, rescale1a.id, side_1="output", side_2="input")   # sum1_id == d1_sum, already MASKED
rescale1b = ArithmeticCombinator(id="d1_rescale_b", position=(DOT_X + 41, DOT_Y + 60), first_operand="signal-T", operation="/", second_operand=SQRT_HEAD_DIM, output_signal="signal-T")
bp.entities.append(rescale1b)
bp.add_circuit_connection(RED, rescale1a.id, rescale1b.id, side_1="output", side_2="input")
score1_src, score1_src_pos = rescale1b.id, rescale1b.position

# ---- score merge: score0 (signal-S) + score1 (signal-T) onto ONE relay.
# rescale0b -> score_merge is a short direct wire (8 down the x=DOT_X+41
# column); score1 comes UP the same empty column via one clean bridge. ----
score_merge = ArithmeticCombinator(id="score_merge", position=(DOT_X + 41, DOT_Y + 8), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(score_merge)
bp.add_circuit_connection(RED, rescale0b.id, score_merge.id, side_1="output", side_2="input")
bridge_to(score1_src, score1_src_pos, score_merge.id, score_merge.position, RED)

# ---- max(score0, score1): pairwise-decider argmax. ONE score bridge in. ----
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
bp.add_circuit_connection(RED, max_ge.id, max_lt.id, side_1="input", side_2="input")
route_L(score_merge.id, score_merge.position, max_ge.id, max_ge.position, RED, lane_x=DOT_X + 47, approach=-4)

max_collect = ArithmeticCombinator(id="max_collect", position=(MAX_X + 20, MAX_Y + 6), first_operand="signal-S", operation="+", second_operand="signal-T", output_signal="signal-U")
bp.entities.append(max_collect)
bridge_to(max_ge.id, max_ge.position, max_collect.id, max_collect.position, RED)
bridge_to(max_lt.id, max_lt.position, max_collect.id, max_collect.position, RED)

# ---- shift_feed: S,T (from the max input net) + U (from max_collect out)
# onto ONE relay -> ONE bridge into SHIFT. ----
shift_feed = ArithmeticCombinator(id="shift_feed", position=(MAX_X, MAX_Y + 12), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(shift_feed)
bp.add_circuit_connection(RED, max_lt.id, shift_feed.id, side_1="input", side_2="input")     # S, T (max_lt.in == max_ge.in)
bridge_to(max_collect.id, max_collect.position, shift_feed.id, shift_feed.position, RED)      # U

# ---- shifted_t = score_t - max_score; idx_t = trunc_div(-shifted_t, WIDTH_FP) ----
shift0 = ArithmeticCombinator(id="shift0", position=(SHIFT_X, SHIFT_Y), first_operand="signal-S", operation="-", second_operand="signal-U", output_signal="signal-V")
bp.entities.append(shift0)
bridge_to(shift_feed.id, shift_feed.position, shift0.id, shift0.position, RED)
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

# ---- exp ROM: two copies addressed by idx0/idx1 on GREEN, value on RED as signal-X. ----
(exp0_entry_id, exp0_entry_pos), (exp0_out_id, exp0_out_pos) = build_addressed_rom(
    "exp0", EXP_TABLE, cond_signal="signal-W", out_signal="signal-X", origin_x=EXP0_X, origin_y=EXP0_Y, rows_per_col=25)
bridge_to(idx0.id, idx0.position, exp0_entry_id, exp0_entry_pos, GREEN)

(exp1_entry_id, exp1_entry_pos), (exp1_out_id, exp1_out_pos) = build_addressed_rom(
    "exp1", EXP_TABLE, cond_signal="signal-W", out_signal="signal-X", origin_x=EXP1_X, origin_y=EXP1_Y, rows_per_col=25)
bridge_to(idx1.id, idx1.position, exp1_entry_id, exp1_entry_pos, GREEN)

exp0_relay = ArithmeticCombinator(id="exp0_relay", position=(EXP0_X, SOFT_Y), first_operand="signal-X", operation="+", second_operand=0, output_signal="signal-Y")
bp.entities.append(exp0_relay)
bridge_to(exp0_out_id, exp0_out_pos, exp0_relay.id, exp0_relay.position, RED)
exp1_relay = ArithmeticCombinator(id="exp1_relay", position=(EXP1_X, SOFT_Y), first_operand="signal-X", operation="+", second_operand=0, output_signal="signal-Z")
bp.entities.append(exp1_relay)
bridge_to(exp1_out_id, exp1_out_pos, exp1_relay.id, exp1_relay.position, RED)

# ---- sum_exp, weight0, weight1 ----
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

w1_a = ArithmeticCombinator(id="w1_a", position=(SOFT_X + 10, SOFT_Y + 12), first_operand="signal-Z", operation="*", second_operand=SCALE, output_signal="signal-7")
bp.entities.append(w1_a)
bp.add_circuit_connection(RED, w0_a.id, w1_a.id, side_1="input", side_2="input")
w1_b = ArithmeticCombinator(id="w1_b", position=(SOFT_X + 18, SOFT_Y + 12), first_operand="signal-7", operation="/", second_operand="signal-0", output_signal="signal-3")
bp.entities.append(w1_b)
bp.add_circuit_connection(RED, w1_a.id, w1_b.id, side_1="output", side_2="input")
bp.add_circuit_connection(RED, w0_b.id, w1_b.id, side_1="input", side_2="input")

# ---- out_i = trunc_div(weight0*V0_i + weight1*V1_i, SCALE), i=0..3 ----
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

# ============================================================================
# PARAMETRIZED OUTPUT: per-position gated latches -> ATTN_OUT buffer (counter #3).
#   out_i (OUT_X+12) -> agate_p (OUT_X+16 / +19) -> alat_p (same x, +2.5 y)
#   a_ctldist_i (OUT_X+22) carries pos+tmod;  counter #3 at OCTL_X=OUT_X+28
# ============================================================================
AGATE0_X = OUT_X + 16
CTLDIST_X = OUT_X + 22
OCTL_X = OUT_X + 28
o_tctr = ArithmeticCombinator(id="o_tctr", position=(OCTL_X, OUT_Y - 12.0), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
bp.entities.append(o_tctr)
bp.add_circuit_connection(RED, "o_tctr", "o_tctr", side_1="output", side_2="input")
o_sh = ArithmeticCombinator(id="o_sh", position=(OCTL_X + 3, OUT_Y - 12.0), first_operand=CLK_SIG, operation="-", second_operand=OFFSET_ATT, output_signal=SH_SIG)
bp.entities.append(o_sh)
bp.add_circuit_connection(RED, "o_tctr", "o_sh", side_1="output", side_2="input")
o_pos = ArithmeticCombinator(id="o_pos", position=(OCTL_X, OUT_Y - 9.0), first_operand=SH_SIG, operation="/", second_operand=K_ATT, output_signal=POS_SIG)
bp.entities.append(o_pos)
bp.add_circuit_connection(RED, "o_sh", "o_pos", side_1="output", side_2="input")
o_tmod = ArithmeticCombinator(id="o_tmod", position=(OCTL_X + 3, OUT_Y - 9.0), first_operand=SH_SIG, operation="%", second_operand=K_ATT, output_signal=TMOD_SIG)
bp.entities.append(o_tmod)
bp.add_circuit_connection(RED, "o_sh", "o_tmod", side_1="output", side_2="input")
o_ctlmerge = ArithmeticCombinator(id="o_ctlmerge", position=(OCTL_X, OUT_Y - 6.0), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(o_ctlmerge)
bp.add_circuit_connection(GREEN, "o_pos", "o_ctlmerge", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "o_tmod", "o_ctlmerge", side_1="output", side_2="input")

prev_cd = "o_ctlmerge"
for i in range(DIM):
    cd = f"a_ctldist_{i}"
    bp.entities.append(ArithmeticCombinator(id=cd, position=(CTLDIST_X, OUT_Y + i * 6), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
    bp.add_circuit_connection(GREEN, prev_cd, cd, side_1="output", side_2="input")
    prev_cd = cd

for i in range(DIM):
    gy = OUT_Y + i * 6
    for p in range(T):
        ag = f"agate_{p}_{i}"
        bp.entities.append(DeciderCombinator(
            id=ag, position=(AGATE0_X + p * 3, gy),
            conditions=[
                DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=p, compare_type="and"),
                DeciderCombinator.Condition(first_signal=TMOD_SIG, comparator="=", constant=PULSE, compare_type="and"),
            ],
            outputs=[DeciderCombinator.Output(signal="signal-Y", copy_count_from_input=True)],
        ))
        bp.add_circuit_connection(RED, f"out_{i}", ag, side_1="output", side_2="input")
        bp.add_circuit_connection(GREEN, f"a_ctldist_{i}", ag, side_1="output", side_2="input")
        al = f"alat_{p}_{i}"
        bp.entities.append(ArithmeticCombinator(id=al, position=(AGATE0_X + p * 3, gy + 2.5), first_operand=ABUF_SIG, operation="+", second_operand="signal-Y", output_signal=ABUF_SIG))
        bp.add_circuit_connection(RED, al, al, side_1="output", side_2="input")
        bp.add_circuit_connection(RED, ag, al, side_1="output", side_2="input")

print(f"Logic entities before power: {len(bp.entities)}")

# ============================================================================
# GEN-TIME GATES: near-overlap scan (revive-merge risk) + draftsman warnings.
# ============================================================================
_combs = []
for i, e in enumerate(bp.entities):
    if e.name in ("arithmetic-combinator", "decider-combinator", "constant-combinator"):
        eid = getattr(e, "id", None) or f"#{i}"
        _combs.append((eid, e.position.x, e.position.y))
_combs.sort(key=lambda t: t[1])
_overlaps = []
for i in range(len(_combs)):
    _, xi, yi = _combs[i]
    for j in range(i + 1, len(_combs)):
        _, xj, yj = _combs[j]
        if xj - xi >= 1.0:
            break
        if abs(yj - yi) < 2.0:
            _overlaps.append((_combs[i][0], _combs[j][0], round(xi, 2), round(yi, 2), round(xj, 2), round(yj, 2)))
print(f"NEAR-OVERLAP pairs (|dx|<1.0 & |dy|<2.0): {len(_overlaps)}")
for o in _overlaps[:60]:
    print("   ", o)

# ---- power: substation grid, legendary quality, occupancy-checked. ----
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
sub_lattice = {}
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

print(f"Power: substation grid {n_rows_p}x{n_cols_p}, {skipped} lattice points skipped")

power_links = 0
power_link_skipped = 0
for (r, c), (sub_id, pos_a) in sub_lattice.items():
    for nr, nc in ((r, c + 1), (r + 1, c)):
        neighbor = sub_lattice.get((nr, nc))
        if neighbor is None:
            continue
        neighbor_id, pos_b = neighbor
        if math.hypot(pos_b[0] - pos_a[0], pos_b[1] - pos_a[1]) > 18:
            power_link_skipped += 1
            continue
        bp.add_power_connection(sub_id, neighbor_id)
        power_links += 1
print(f"Power: {power_links} substation-substation connections added ({power_link_skipped} skipped)")
print(f"Total entities incl. power: {len(bp.entities)}")

bp_string = bp.to_string()
with open("stage2_attention_param_blueprint.txt", "w") as f:
    f.write(bp_string)

# id<->position map for the offline network analyzer (Factorio blueprints
# don't carry draftsman's string ids).
_idmap = []
for e in bp.entities:
    eid = getattr(e, "id", None)
    if not eid:
        continue
    _idmap.append({"id": eid, "x": round(e.position.x, 3), "y": round(e.position.y, 3), "name": e.name})
with open("stage2_attention_param_ids.json", "w") as f:
    json.dump(_idmap, f)

print(f"draftsman warnings: {len(_caught_warnings)}")
for w in _caught_warnings[:40]:
    print("   ", w)

print(f"Blueprint string length: {len(bp_string)}")
print()
print(f"T={T}  K_ATT={K_ATT}  PULSE={PULSE}  BIGMASK={BIGMASK}  OFFSET_ATT={OFFSET_ATT}")
print(f"Q_FP_ALL = {Q_FP_ALL}")
print(f"EXPECT alat_p_i ({ABUF_SIG}):")
for p in range(T):
    print(f"  pos {p}: {ATTN_OUT_EXPECTED[p]}   (alat_{p}_0..alat_{p}_3)")
print(f"sweep: pos p latched at tick ~ p*{K_ATT}+{PULSE}; read after ~{T*K_ATT+400} ticks")
print("Saved stage2_attention_param_blueprint.txt")
