"""
Parametrized (spatial, non-multiplexed) matmul+bias block for the Sequencer
DAG - QKV projection instance (N_IN=4, N_OUT=12).

The ORIGINAL matmul unit (stage2_matmul_test_export.py, Решение 26, closed
11.08.2026) is a time-multiplexed single ALU with a build-time-fixed
address sweep and hand-solved tick-padding to keep 4 independent signal
paths (W, X, O-index, P-product) in lockstep - a deliberate ENTITY-COUNT
optimization for the eventual full-scale model (dim=32+), not something
the tiny smoke config (dim=4) needs. It's also position-0-only: no notion
of a live position sweep at all.

For the smoke-test DAG, per the architecture note in
sequencer_live_build_progress ("для смок-конфига не нужны ни
resettable-счётчик, ни живая STATE-машина"), a SPATIAL matmul - one
physical dot-product+adder-tree per output neuron, all N_OUT computed in
parallel every tick - is simpler, has zero timing-padding to get wrong,
and reuses the EXACT dot_terms/adder_tree/output-latch machinery already
proven live this session in stage2_attention_param.py. Weights and biases
are build-time-fixed model parameters (not autoregressively updated), so
each term is a plain CONSTANT multiply (X_i * q(W[i][o])) - no weight ROM,
no second live signal, none of dot_terms' original two-live-vectors
complexity is needed here at all.

Reference: stage2_sequencer_ref.json / stage2_smoke_weights.json.
Expected (T=2, concatenated q|k|v per position):
  pos0 = [-8,-8,0,-15, 46,-40,-7,40, 2,-6,4,38]
  pos1 = [5,-35,41,11, -11,-19,14,-53, -32,-84,10,2]
"""
import json
import math
import warnings

_caught_warnings = []
def _showwarning(message, *args, **kwargs):
    _caught_warnings.append(str(message))
warnings.showwarning = _showwarning

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

with open("stage2_smoke_weights.json") as f:
    W_ = json.load(f)
with open("stage2_sequencer_ref.json") as f:
    SEQ = json.load(f)

SCALE = 100
DIM = W_["dim"]           # N_IN = 4
N_OUT = 3 * DIM           # QKV concatenated = 12
Wqkv = W_["Wqkv"]         # [N_IN][N_OUT]
bqkv = W_["bqkv"]         # [N_OUT]
H1_FP = SEQ["h1_fp"]      # live input buffer for the isolated test (T x DIM)
T = len(H1_FP)
EXPECTED = [SEQ["q_fp"][p] + SEQ["k_fp"][p] + SEQ["v_fp"][p] for p in range(T)]


def q(x):
    return int(round(x * SCALE))


K_MM = 1000
PULSE = K_MM * 7 // 10   # 700
OFFSET_MM = 0
CLK_SIG, SH_SIG, POS_SIG, TMOD_SIG = "signal-red", "signal-green", "signal-8", "signal-9"
X_SIGS = ["signal-A", "signal-B", "signal-C", "signal-D"][:DIM]
OBUF_SIG = "signal-grey"

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "Matmul parametrized (spatial dot-product+bias per output neuron, live input buffer)"

RELAY_HOP = 7
_bridge_ctr = 0


def _occupied_points():
    pts = []
    for e in bp.entities:
        p = e.position
        pts.append((p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1]))
    return pts


def _nudge_clear(pos, occ, path_dir, rx=1.4, ry=2.5, max_off=4.0):
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
        nom = (tx, ty) if last else (px + (tx - px) / rem * hop, py + (ty - py) / rem * hop)
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


def bridge_to(from_id, from_pos, target_id, target_pos, color, standoff=3, hop=RELAY_HOP, side_1="output", side_2="input"):
    prev_id, prev_pos = from_id, from_pos
    tx, ty = target_pos
    fx, fy = prev_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist <= standoff + 1.5:
        bp.add_circuit_connection(color, prev_id, target_id, side_1=side_1, side_2=side_2)
        return
    t = (dist - standoff) / dist
    stop_pos = (fx + (tx - fx) * t, fy + (ty - fy) * t)
    last_id, _, _ = bridge(prev_id, prev_pos, stop_pos, color, hop=hop)
    bp.add_circuit_connection(color, last_id, target_id, side_1=side_1, side_2=side_2)


# ---- well-separated block origins ----
IN_X, IN_Y = 2000, 0        # counter #1, X-buffer + mux
MM_X, MM_Y = 2000, 200      # 12 output-neuron dot-product+bias+rescale chains
OUT_X, OUT_Y = 2000, 500    # counter #2, output gates/latches

# ============================================================================
# Counter #1 + X-buffer/mux (position-swept live input, same recipe as
# stage2_embed_param.py's tok/pos ROM addressing and stage2_attention_
# param.py's Q-mux).
# ============================================================================
e_tctr = ArithmeticCombinator(id="e_tctr", position=(IN_X + 0.5, IN_Y - 12.0), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
bp.entities.append(e_tctr)
bp.add_circuit_connection(RED, "e_tctr", "e_tctr", side_1="output", side_2="input")
e_sh = ArithmeticCombinator(id="e_sh", position=(IN_X + 3.5, IN_Y - 12.0), first_operand=CLK_SIG, operation="-", second_operand=OFFSET_MM, output_signal=SH_SIG)
bp.entities.append(e_sh)
bp.add_circuit_connection(RED, "e_tctr", "e_sh", side_1="output", side_2="input")
e_pos = ArithmeticCombinator(id="e_pos", position=(IN_X + 0.5, IN_Y - 9.0), first_operand=SH_SIG, operation="/", second_operand=K_MM, output_signal=POS_SIG)
bp.entities.append(e_pos)
bp.add_circuit_connection(RED, "e_sh", "e_pos", side_1="output", side_2="input")

POSDIST_X, XBUF0_X, XMUX0_X, XSEL_X = IN_X - 14, IN_X - 12, IN_X - 7.0, IN_X - 3.0
prev_pd = None
for i in range(DIM):
    pd = f"x_posdist_{i}"
    bp.entities.append(ArithmeticCombinator(id=pd, position=(POSDIST_X, IN_Y + i * 6), first_operand=POS_SIG, operation="+", second_operand=0, output_signal=POS_SIG))
    if prev_pd is None:
        bridge_to("e_pos", (IN_X + 0.5, IN_Y - 9.0), pd, (POSDIST_X, IN_Y), GREEN)
    else:
        bp.add_circuit_connection(GREEN, prev_pd, pd, side_1="output", side_2="input")
    prev_pd = pd

for i in range(DIM):
    sig = X_SIGS[i]
    gy = IN_Y + i * 6
    for p in range(T):
        xb = ConstantCombinator(id=f"xbuf_{p}_{i}", tile_position=(int(XBUF0_X) + p * 2, int(gy)))
        xb.set_signal(index=0, name=sig, count=H1_FP[p][i])
        bp.entities.append(xb)
        mux = DeciderCombinator(
            id=f"xmux_{p}_{i}", position=(XMUX0_X + p * 1.5, gy),
            conditions=[DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=p)],
            outputs=[DeciderCombinator.Output(signal=sig, copy_count_from_input=True)],
        )
        bp.entities.append(mux)
        bp.add_circuit_connection(RED, f"xbuf_{p}_{i}", f"xmux_{p}_{i}", side_2="input")
        bp.add_circuit_connection(GREEN, f"x_posdist_{i}", f"xmux_{p}_{i}", side_1="output", side_2="input")
    xsel = ArithmeticCombinator(id=f"xsel_{i}", position=(XSEL_X, gy), first_operand=sig, operation="+", second_operand=0, output_signal=sig)
    bp.entities.append(xsel)
    for p in range(T):
        bp.add_circuit_connection(RED, f"xmux_{p}_{i}", f"xsel_{i}", side_1="output", side_2="input")
    # merge all xsel_i OUTPUTS onto ONE shared bus (direct wire, 6 tiles
    # apart) - each xsel_i only carries ITS OWN dim signal until joined,
    # a single tap downstream needs all DIM signals present simultaneously
    # (the SAME "N sources must share one network" pattern as everywhere
    # else - a bug caught here BEFORE building, not after this time).
    if i > 0:
        bp.add_circuit_connection(RED, f"xsel_{i - 1}", f"xsel_{i}", side_1="output", side_2="output")

def adder_tree(term_ids, dest_prefix, origin_x, origin_y, out_sig="signal-P"):
    """Verbatim from stage2_attention_param.py: pairwise adder tree for
    N_IN=4 (2 pairwise adds, 1 final add), each a plain pass-through since
    the shared input network already auto-sums same-named signals from
    a_id/b_id (re-adding it to itself was the 06.09.2026 self-doubling bug)."""
    a_id, a_pos = term_ids[0]
    b_id, b_pos = term_ids[1]
    s01 = ArithmeticCombinator(id=f"{dest_prefix}_s01", position=(origin_x, origin_y), first_operand=out_sig, operation="+", second_operand=0, output_signal=out_sig)
    bp.entities.append(s01)
    bridge_to(a_id, a_pos, s01.id, s01.position, RED)
    bridge_to(b_id, b_pos, s01.id, s01.position, RED)

    c_id, c_pos = term_ids[2]
    d_id, d_pos = term_ids[3]
    s23 = ArithmeticCombinator(id=f"{dest_prefix}_s23", position=(origin_x, origin_y + 6), first_operand=out_sig, operation="+", second_operand=0, output_signal=out_sig)
    bp.entities.append(s23)
    bridge_to(c_id, c_pos, s23.id, s23.position, RED)
    bridge_to(d_id, d_pos, s23.id, s23.position, RED)

    total = ArithmeticCombinator(id=f"{dest_prefix}_sum", position=(origin_x + 6, origin_y + 3), first_operand=out_sig, operation="+", second_operand=0, output_signal=out_sig)
    bp.entities.append(total)
    bridge_to(s01.id, s01.position, total.id, total.position, RED)
    bridge_to(s23.id, s23.position, total.id, total.position, RED)
    return total.id, total.position


# ============================================================================
# Counter #2 (output-gate pulse), placed right next to the neuron block
# (not a separate far-away OUT block) - its GREEN pos/tmod spine then only
# has to run alongside the 12 neuron rows, never crossing back and forth
# across the whole map (the class of collision that produced 143
# near-overlaps in the first draft of this file).
# ============================================================================
ROW_DY = 30
BUS_X = MM_X - 15    # dedicated X-bus corridor, nothing else ever occupies it
CTL_X = MM_X + 24     # dedicated control-spine corridor, just left of the gates
CTL2_X, CTL2_Y = MM_X + 40, MM_Y - 20

o_tctr = ArithmeticCombinator(id="o_tctr", position=(CTL2_X, CTL2_Y), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
bp.entities.append(o_tctr)
bp.add_circuit_connection(RED, "o_tctr", "o_tctr", side_1="output", side_2="input")
o_sh = ArithmeticCombinator(id="o_sh", position=(CTL2_X + 3, CTL2_Y), first_operand=CLK_SIG, operation="-", second_operand=OFFSET_MM, output_signal=SH_SIG)
bp.entities.append(o_sh)
bp.add_circuit_connection(RED, "o_tctr", "o_sh", side_1="output", side_2="input")
o_pos = ArithmeticCombinator(id="o_pos", position=(CTL2_X, CTL2_Y + 3), first_operand=SH_SIG, operation="/", second_operand=K_MM, output_signal=POS_SIG)
bp.entities.append(o_pos)
bp.add_circuit_connection(RED, "o_sh", "o_pos", side_1="output", side_2="input")
o_tmod = ArithmeticCombinator(id="o_tmod", position=(CTL2_X + 3, CTL2_Y + 3), first_operand=SH_SIG, operation="%", second_operand=K_MM, output_signal=TMOD_SIG)
bp.entities.append(o_tmod)
bp.add_circuit_connection(RED, "o_sh", "o_tmod", side_1="output", side_2="input")
o_ctlmerge = ArithmeticCombinator(id="o_ctlmerge", position=(CTL2_X, CTL2_Y + 6), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(o_ctlmerge)
bp.add_circuit_connection(GREEN, "o_pos", "o_ctlmerge", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "o_tmod", "o_ctlmerge", side_1="output", side_2="input")

# ============================================================================
# 12 neuron rows, EACH fully self-contained: 4 terms -> adder_tree -> bias
# -> rescale -> 2 gates -> 2 latches, all in the SAME row. Only two things
# are shared across rows (the X-bus and the pos/tmod control), and each is
# a dedicated vertical spine tapped ONCE per row with a SHORT same-row hop -
# never a long bridge crossing another row's territory.
# ============================================================================
prev_bus_id, prev_ctl_id = None, None
mm_out_ids = []
for o in range(N_OUT):
    ny = MM_Y + o * ROW_DY

    group = []
    for i in range(DIM):
        tid = f"mm_term_{o}_{i}"
        e = ArithmeticCombinator(id=tid, position=(MM_X + i * 2, ny), first_operand=X_SIGS[i], operation="*", second_operand=q(Wqkv[i][o]), output_signal="signal-P")
        bp.entities.append(e)
        if i > 0:
            bp.add_circuit_connection(RED, group[-1][0], tid, side_1="input", side_2="input")
        group.append((tid, e.position))

    # bus spine: ONE source (the X-bus, tapped once at row 0) fanning out to
    # 12 consumers - a plain one-way relay cascade (each row recomputes and
    # forwards, like bridge()'s own hops), NOT an output-output merge (that
    # trick is for genuinely multiple sources, e.g. xsel_0..3 above).
    brid, bpos = f"mm_bus_{o}", (BUS_X, ny)
    bp.entities.append(ArithmeticCombinator(id=brid, position=bpos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
    if prev_bus_id is not None:
        bridge_to(prev_bus_id[0], prev_bus_id[1], brid, bpos, RED)
    bridge_to(brid, bpos, group[0][0], group[0][1], RED)
    prev_bus_id = (brid, bpos)

    sum_id, sum_pos = adder_tree(group, f"mm{o}", MM_X + 10, ny)
    bias_id, bias_pos = f"mm_bias_{o}", (MM_X + 18, ny + 3)
    bp.entities.append(ArithmeticCombinator(id=bias_id, position=bias_pos, first_operand="signal-P", operation="+", second_operand=q(bqkv[o]) * SCALE, output_signal="signal-P"))
    bp.add_circuit_connection(RED, sum_id, bias_id, side_1="output", side_2="input")
    out_id, out_pos = f"mm_out_{o}", (MM_X + 22, ny + 3)
    bp.entities.append(ArithmeticCombinator(id=out_id, position=out_pos, first_operand="signal-P", operation="/", second_operand=SCALE, output_signal="signal-Y"))
    bp.add_circuit_connection(RED, bias_id, out_id, side_1="output", side_2="input")
    mm_out_ids.append((out_id, out_pos))

    crid, cpos = f"mm_ctl_{o}", (CTL_X, ny)
    bp.entities.append(ArithmeticCombinator(id=crid, position=cpos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
    if prev_ctl_id is None:
        bridge_to("o_ctlmerge", (CTL2_X, CTL2_Y + 6), crid, cpos, GREEN)
    else:
        bridge_to(prev_ctl_id[0], prev_ctl_id[1], crid, cpos, GREEN)
    prev_ctl_id = (crid, cpos)

    for p in range(T):
        gx = MM_X + 26 + p * 4
        ag = f"ogate_{p}_{o}"
        bp.entities.append(DeciderCombinator(
            id=ag, position=(gx, ny + 3),
            conditions=[
                DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=p, compare_type="and"),
                DeciderCombinator.Condition(first_signal=TMOD_SIG, comparator="=", constant=PULSE, compare_type="and"),
            ],
            outputs=[DeciderCombinator.Output(signal="signal-Y", copy_count_from_input=True)],
        ))
        bp.add_circuit_connection(RED, out_id, ag, side_1="output", side_2="input")
        bp.add_circuit_connection(GREEN, crid, ag, side_1="output", side_2="input")
        al = f"olat_{p}_{o}"
        bp.entities.append(ArithmeticCombinator(id=al, position=(gx, ny + 6), first_operand=OBUF_SIG, operation="+", second_operand="signal-Y", output_signal=OBUF_SIG))
        bp.add_circuit_connection(RED, al, al, side_1="output", side_2="input")
        bp.add_circuit_connection(RED, ag, al, side_1="output", side_2="input")

bridge_to("xsel_0", (XSEL_X, IN_Y), "mm_bus_0", (BUS_X, MM_Y), RED)

print(f"Logic entities before power: {len(bp.entities)}")

# ============================================================================
# GEN-TIME GATES
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
for o_ in _overlaps[:60]:
    print("   ", o_)

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
with open("stage2_matmul_param_blueprint.txt", "w") as f:
    f.write(bp_string)

_idmap = []
for e in bp.entities:
    eid = getattr(e, "id", None)
    if not eid:
        continue
    _idmap.append({"id": eid, "x": round(e.position.x, 3), "y": round(e.position.y, 3), "name": e.name})
with open("stage2_matmul_param_ids.json", "w") as f:
    json.dump(_idmap, f)

print(f"draftsman warnings: {len(_caught_warnings)}")
for w_ in _caught_warnings[:40]:
    print("   ", w_)

print(f"Blueprint string length: {len(bp_string)}")
print()
print(f"T={T} DIM={DIM} N_OUT={N_OUT} K_MM={K_MM} PULSE={PULSE}")
print("EXPECT olat_p_o (signal-grey):")
for p in range(T):
    print(f"  pos {p}: {EXPECTED[p]}")
print("Saved stage2_matmul_param_blueprint.txt")
