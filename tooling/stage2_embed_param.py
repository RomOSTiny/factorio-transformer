"""
Parametrized Embed block (Этап 2, механика 4 - Sequencer, first DAG stage).

Unlike LayerNorm/Attention (which existed as fixed blocks before being
parametrized), Embed never had a live circuit at all - this is the first
build. Two-level ROM lookup, addressed by a build-time-staggered position
sweep (same free-running-counter + output-latch recipe proven live this
session for Attention):

  pos -> token_id (small ConstantCombinator table, addressed by pos -
         stands in for a real "token sequence buffer"; a live buffer is
         only needed once autoregression exists, a later phase)
  token_id -> tok_emb[token_id]   (VOCAB rows, DIM signals per row)
  pos -> pos_emb[pos]             (T rows, DIM signals per row)
  x[pos] = tok_emb[token_id] + pos_emb[pos]   (free: both ROMs write the
         SAME DIM signal names A..D, Factorio auto-sums same-named
         signals arriving from multiple sources on one wire)

x[pos] is then captured into a 2x4 output-latch buffer (agate/alat
pattern from stage2_attention_param.py) - this is the "x_i" live buffer
the LayerNorm block's own input stage bridges from once the DAG is
assembled.

Reference: stage2_sequencer_ref.json / stage2_smoke_weights.json.
Expected: x_fp = [[-30,-10,30,0], [-20,-40,-20,60]] (tokens=[0,2]).
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

with open("stage2_smoke_weights.json") as f:
    W = json.load(f)
with open("stage2_sequencer_ref.json") as f:
    SEQ = json.load(f)

SCALE = 100
DIM = W["dim"]
VOCAB = W["vocab_size"]
TOKENS = W["tokens"]
T = len(TOKENS)
TOK_EMB = W["tok_emb"]
POS_EMB = W["pos_emb"]
EXPECTED_X_FP = SEQ["x_fp"]


def q(x):
    return int(round(x * SCALE))


K_EMB = 1000
PULSE = K_EMB * 7 // 10   # 700
OFFSET_EMB = 0            # isolated test: sweep from revival, no upstream
CLK_SIG, SH_SIG, POS_SIG, TMOD_SIG = "signal-red", "signal-green", "signal-8", "signal-9"
TOKID_SIG = "signal-W"
DIM_SIGS = ["signal-A", "signal-B", "signal-C", "signal-D"][:DIM]
EBUF_SIG = "signal-grey"

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "Embed parametrized (position sweep, 2-level ROM lookup, live output buffer)"

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


# ---- well-separated block origins ----
IN_X, IN_Y = 2000, 0      # counter #1, tokid ROM, tokemb ROM, posemb ROM
OUT_X, OUT_Y = 2000, 200  # counter #2, output gates/latches

# ============================================================================
# Counter #1 (position sweep, addresses both ROM stages)
# ============================================================================
e_tctr = ArithmeticCombinator(id="e_tctr", position=(IN_X + 0.5, IN_Y - 12.0), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
bp.entities.append(e_tctr)
bp.add_circuit_connection(RED, "e_tctr", "e_tctr", side_1="output", side_2="input")
e_sh = ArithmeticCombinator(id="e_sh", position=(IN_X + 3.5, IN_Y - 12.0), first_operand=CLK_SIG, operation="-", second_operand=OFFSET_EMB, output_signal=SH_SIG)
bp.entities.append(e_sh)
bp.add_circuit_connection(RED, "e_tctr", "e_sh", side_1="output", side_2="input")
e_pos = ArithmeticCombinator(id="e_pos", position=(IN_X + 0.5, IN_Y - 9.0), first_operand=SH_SIG, operation="/", second_operand=K_EMB, output_signal=POS_SIG)
bp.entities.append(e_pos)
bp.add_circuit_connection(RED, "e_sh", "e_pos", side_1="output", side_2="input")

# ============================================================================
# token-id lookup: pos -> token_id (T rows, stands in for a token buffer)
# ============================================================================
tokid_read_ids = []
for p in range(T):
    store = ConstantCombinator(id=f"tokid_store_{p}", tile_position=(IN_X, IN_Y + p * 6))
    store.set_signal(index=0, name=TOKID_SIG, count=TOKENS[p])
    bp.entities.append(store)
    read = DeciderCombinator(
        id=f"tokid_read_{p}", position=(IN_X + 3, IN_Y + p * 6),
        conditions=[DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=p)],
        outputs=[DeciderCombinator.Output(signal=TOKID_SIG, copy_count_from_input=True)],
    )
    bp.entities.append(read)
    bp.add_circuit_connection(RED, f"tokid_store_{p}", f"tokid_read_{p}", side_2="input")
    bridge_to("e_pos", (IN_X + 0.5, IN_Y - 9.0), f"tokid_read_{p}", (IN_X + 3, IN_Y + p * 6), GREEN)
    tokid_read_ids.append((f"tokid_read_{p}", (IN_X + 3, IN_Y + p * 6)))

# chain the tokid_read outputs onto one shared "current token id" network.
# output-output (not bridge_to's output-input!) so multiple sources genuinely
# sum on one node - same fix and same reasoning as the tokemb/posemb merge
# below (a bridged link only relays one-way; read from whichever entity is
# downstream of every bridge segment in the chain - here T=2 rows are close
# enough that no bridge is needed at all, so any point in the chain works).
for i in range(1, len(tokid_read_ids)):
    a_id, a_pos = tokid_read_ids[i - 1]
    b_id, b_pos = tokid_read_ids[i]
    if math.hypot(b_pos[0] - a_pos[0], b_pos[1] - a_pos[1]) <= 9:
        bp.add_circuit_connection(RED, a_id, b_id, side_1="output", side_2="output")
    else:
        last_id, last_pos, _ = bridge(a_id, a_pos, b_pos, RED)
        bp.add_circuit_connection(RED, last_id, b_id, side_1="output", side_2="output")
tokid_bus_id, tokid_bus_pos = tokid_read_ids[-1]

# ============================================================================
# token embedding ROM: token_id -> DIM signals A..D (VOCAB rows)
# ============================================================================
TOKEMB_X = IN_X + 20
tokemb_read_ids = []
for t in range(VOCAB):
    store = ConstantCombinator(id=f"tokemb_store_{t}", tile_position=(TOKEMB_X, IN_Y + t * 6))
    for d in range(DIM):
        store.set_signal(index=d, name=DIM_SIGS[d], count=q(TOK_EMB[t][d]))
    bp.entities.append(store)
    read = DeciderCombinator(
        id=f"tokemb_read_{t}", position=(TOKEMB_X + 3, IN_Y + t * 6),
        conditions=[DeciderCombinator.Condition(first_signal=TOKID_SIG, comparator="=", constant=t)],
        outputs=[DeciderCombinator.Output(signal=sig, copy_count_from_input=True) for sig in DIM_SIGS],
    )
    bp.entities.append(read)
    bp.add_circuit_connection(RED, f"tokemb_store_{t}", f"tokemb_read_{t}", side_2="input")
    bridge_to(tokid_bus_id, tokid_bus_pos, f"tokemb_read_{t}", (TOKEMB_X + 3, IN_Y + t * 6), GREEN)
    tokemb_read_ids.append((f"tokemb_read_{t}", (TOKEMB_X + 3, IN_Y + t * 6)))

# ============================================================================
# position embedding ROM: pos -> DIM signals A..D (T rows). SAME signal
# names as tok_emb - Factorio auto-sums same-named signals from multiple
# sources once both outputs share one network, giving x[pos] = tok_emb+pos_emb
# for free, no adder combinator needed.
# ============================================================================
POSEMB_X = IN_X + 40
posemb_read_ids = []
for p in range(T):
    store = ConstantCombinator(id=f"posemb_store_{p}", tile_position=(POSEMB_X, IN_Y + p * 6))
    for d in range(DIM):
        store.set_signal(index=d, name=DIM_SIGS[d], count=q(POS_EMB[p][d]))
    bp.entities.append(store)
    read = DeciderCombinator(
        id=f"posemb_read_{p}", position=(POSEMB_X + 3, IN_Y + p * 6),
        conditions=[DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=p)],
        outputs=[DeciderCombinator.Output(signal=sig, copy_count_from_input=True) for sig in DIM_SIGS],
    )
    bp.entities.append(read)
    bp.add_circuit_connection(RED, f"posemb_store_{p}", f"posemb_read_{p}", side_2="input")
    bridge_to("e_pos", (IN_X + 0.5, IN_Y - 9.0), f"posemb_read_{p}", (POSEMB_X + 3, IN_Y + p * 6), GREEN)
    posemb_read_ids.append((f"posemb_read_{p}", (POSEMB_X + 3, IN_Y + p * 6)))

# ---- merge: all tokemb_read + posemb_read OUTPUTS share ONE network (x[pos]).
# Chain the sources' OUTPUT sides together directly (side_1=side_2="output")
# instead of bridging each of the 6 individually into a shared hub - 6
# independent bridges converging on one point is the "N sources, 1 target"
# collision class (their relay chains run close/parallel and overlap on
# revive) that caused the x4 bug in Attention; chaining avoids it by only
# needing ONE bridge for the whole merged network.
#
# BUG FOUND LIVE (15.09.2026): a bridge() relay chain is a ONE-WAY repeater
# (it reads its input network and re-broadcasts on a SEPARATE output
# network with 1-tick-per-hop delay) - it does NOT splice two segments
# into one bidirectional network the way a short direct wire does. Since
# tokemb_read_3 -> posemb_read_0 is far enough to need a bridge, the merge
# is only COMPLETE on the posemb side (downstream of that bridge, where the
# relayed tok_emb value additively joins posemb's own output) - the tokemb
# side (upstream) never sees posemb's contribution flow backward. Reading
# xsum from the chain's FIRST entity (tokemb side) silently dropped
# pos_emb entirely. Fix: read from the chain's LAST entity instead - it is
# downstream of every bridge segment in the chain, so it's the one point
# guaranteed to see every source's contribution. ----
read_chain = tokemb_read_ids + posemb_read_ids
for i in range(1, len(read_chain)):
    a_id, a_pos = read_chain[i - 1]
    b_id, b_pos = read_chain[i]
    if math.hypot(b_pos[0] - a_pos[0], b_pos[1] - a_pos[1]) <= 9:
        bp.add_circuit_connection(RED, a_id, b_id, side_1="output", side_2="output")
    else:
        last_id, last_pos, _ = bridge(a_id, a_pos, b_pos, RED)
        bp.add_circuit_connection(RED, last_id, b_id, side_1="output", side_2="output")
xsum_pos = (IN_X + 60, IN_Y + 30)
bp.entities.append(ArithmeticCombinator(id="xsum", position=xsum_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
bridge_to(read_chain[-1][0], read_chain[-1][1], "xsum", xsum_pos, RED)

# ============================================================================
# Counter #2 + output latches: per-position gated capture of x[pos] into a
# T x DIM buffer (agate/alat pattern from stage2_attention_param.py).
# ============================================================================
o_tctr = ArithmeticCombinator(id="o_tctr", position=(OUT_X, OUT_Y - 12.0), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
bp.entities.append(o_tctr)
bp.add_circuit_connection(RED, "o_tctr", "o_tctr", side_1="output", side_2="input")
o_sh = ArithmeticCombinator(id="o_sh", position=(OUT_X + 3, OUT_Y - 12.0), first_operand=CLK_SIG, operation="-", second_operand=OFFSET_EMB, output_signal=SH_SIG)
bp.entities.append(o_sh)
bp.add_circuit_connection(RED, "o_tctr", "o_sh", side_1="output", side_2="input")
o_pos = ArithmeticCombinator(id="o_pos", position=(OUT_X, OUT_Y - 9.0), first_operand=SH_SIG, operation="/", second_operand=K_EMB, output_signal=POS_SIG)
bp.entities.append(o_pos)
bp.add_circuit_connection(RED, "o_sh", "o_pos", side_1="output", side_2="input")
o_tmod = ArithmeticCombinator(id="o_tmod", position=(OUT_X + 3, OUT_Y - 9.0), first_operand=SH_SIG, operation="%", second_operand=K_EMB, output_signal=TMOD_SIG)
bp.entities.append(o_tmod)
bp.add_circuit_connection(RED, "o_sh", "o_tmod", side_1="output", side_2="input")
o_ctlmerge = ArithmeticCombinator(id="o_ctlmerge", position=(OUT_X, OUT_Y - 6.0), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(o_ctlmerge)
bp.add_circuit_connection(GREEN, "o_pos", "o_ctlmerge", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "o_tmod", "o_ctlmerge", side_1="output", side_2="input")

# 8 gates all need the SAME two source networks (xsum's RED output, o_ctlmerge's
# GREEN output) - the "one source, many destinations" collision class (same
# as Attention's max_ge/max_lt, dot_terms). Fix: chain the gates' INPUT sides
# directly to each other (6 tiles apart) and bridge only ONCE per source, to
# the first gate in the chain.
prev_gate = None
for p in range(T):
    for d in range(DIM):
        gy = OUT_Y + (p * DIM + d) * 6
        ag = f"egate_{p}_{d}"
        bp.entities.append(DeciderCombinator(
            id=ag, position=(OUT_X + 10, gy),
            conditions=[
                DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=p, compare_type="and"),
                DeciderCombinator.Condition(first_signal=TMOD_SIG, comparator="=", constant=PULSE, compare_type="and"),
            ],
            outputs=[DeciderCombinator.Output(signal=DIM_SIGS[d], copy_count_from_input=True)],
        ))
        if prev_gate is None:
            bridge_to("xsum", xsum_pos, ag, (OUT_X + 10, gy), RED)
            bridge_to("o_ctlmerge", (OUT_X, OUT_Y - 6.0), ag, (OUT_X + 10, gy), GREEN)
        else:
            bp.add_circuit_connection(RED, prev_gate, ag, side_1="input", side_2="input")
            bp.add_circuit_connection(GREEN, prev_gate, ag, side_1="input", side_2="input")
        prev_gate = ag
        al = f"elat_{p}_{d}"
        bp.entities.append(ArithmeticCombinator(id=al, position=(OUT_X + 10, gy + 2.5), first_operand=EBUF_SIG, operation="+", second_operand=DIM_SIGS[d], output_signal=EBUF_SIG))
        bp.add_circuit_connection(RED, al, al, side_1="output", side_2="input")
        bp.add_circuit_connection(RED, ag, al, side_1="output", side_2="input")

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
with open("stage2_embed_param_blueprint.txt", "w") as f:
    f.write(bp_string)

_idmap = []
for e in bp.entities:
    eid = getattr(e, "id", None)
    if not eid:
        continue
    _idmap.append({"id": eid, "x": round(e.position.x, 3), "y": round(e.position.y, 3), "name": e.name})
with open("stage2_embed_param_ids.json", "w") as f:
    json.dump(_idmap, f)

print(f"draftsman warnings: {len(_caught_warnings)}")
for w in _caught_warnings[:40]:
    print("   ", w)

print(f"Blueprint string length: {len(bp_string)}")
print()
print(f"T={T} DIM={DIM} VOCAB={VOCAB} K_EMB={K_EMB} PULSE={PULSE} TOKENS={TOKENS}")
print(f"EXPECT elat_p_d ({EBUF_SIG}):")
for p in range(T):
    print(f"  pos {p}: {EXPECTED_X_FP[p]}   (elat_{p}_0..elat_{p}_{DIM - 1})")
print("Saved stage2_embed_param_blueprint.txt")
