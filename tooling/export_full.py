"""
Full classifier export: 50 letter-position input -> 300 syllable detectors
-> hidden layer (32, ReLU) -> output layer (50 topics) -> argmax -> Display
Panel.

ARCHITECTURE NOTE (see PROJECT.md decision log for the full story of how
this was arrived at): a decider combinator can only read from 2 independent
wire networks (red + green) at once, but checking a 3-letter syllable
window needs 3 independent position values. Rather than 2-stage decider
chaining, positions are encoded as NUMBERS (not which-of-26-signals-is-
active) on ONE shared signal name ("signal-check", value 1-26 for a-z, 27
for space) - each position is still its own physically separate wire
(that's what keeps position 3 distinct from position 7), but now a WINDOW
CODE can be computed once per 3-letter window via plain arithmetic:
code = value(pos)*729 + value(pos+1)*27 + value(pos+2), using 3 arithmetic
combinators (one per position in the window, each reading its own single
wire) whose outputs SUM onto one shared per-window signal - the same
"multiple sources summing on a shared wire" trick used throughout this
project, just applied to base-27 positional encoding instead of a weighted
sum. Every syllable detector at that window position then becomes ONE
decider with ONE condition (window code == this syllable's precomputed
code), instead of three conditions across three wires.

This also collapses the relay bus from "50 parallel per-position chains"
down to "one chain relaying all 48 window-code signals together" (via
signal-each, since the 48 codes have distinct names and don't collide when
merged onto one wire) - a big simplification over the first attempt, which
tried to relay raw per-position signals (needing signal-identity
preservation) all the way out to every detector.

Player-facing tradeoff: input is now "type the number 1-26 for each
letter, 27 for space" per position instead of picking a letter icon -
less mnemonic, but the icon-identity approach didn't fit the 2-network
decider limit. A generated cheat sheet (a=1..z=26, space=27) ships
alongside the blueprint.

N_SYLLABLES below controls how many of the 300 trained syllables to
actually build - kept low for a structural smoke test before committing to
the full (large, slow) build.
"""

import json
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, DisplayPanel, ElectricEnergyInterface, ElectricPole
from draftsman.data import signals as signal_data
from draftsman.signatures import Condition

# ---- config ----
N_SYLLABLES = 300  # full build - vocab_syllables.json has exactly 300 entries
INPUT_LEN = 50
N_WINDOWS = INPUT_LEN - 2  # 48
SCALE = 1000
RELAY_HOP = 8  # <= 9 tile wire limit
POS_SPACING = 2
CHECK_SIGNAL = "signal-check"

with open("../training/vocab_syllables.json", encoding="utf-8") as f:
    VOCAB_FULL = json.load(f)
with open("../training/classifier_weights.json", encoding="utf-8") as f:
    weights = json.load(f)
with open("../data/intents_cardputer.json", encoding="utf-8") as f:
    _cardputer = json.load(f)
with open("../data/intents_new_factorio.json", encoding="utf-8") as f:
    _factorio_new = json.load(f)

VOCAB = VOCAB_FULL[:N_SYLLABLES]
CLASSES = weights["classes"]
W1, b1, W2, b2 = weights["W1"], weights["b1"], weights["W2"], weights["b2"]

# CLASSES order is [cardputer intents..., factorio intents..., "fallback"]
# (see training/train_classifier.py) - same source files, same order, so a
# straight name lookup lines every class index up with its response text.
# Picking responses[0] (not random) keeps the export reproducible run to
# run, same principle as everywhere else in this project.
_response_by_class = {i["name"]: i["responses"][0] for i in _cardputer["intents"] + _factorio_new["intents"]}
_response_by_class["fallback"] = _cardputer["fallback"]["responses"][0]
CLASS_RESPONSES = [_response_by_class[c] for c in CLASSES]


def letter_code(ch):
    return 27 if ch == " " else (ord(ch) - ord("a") + 1)


def window_code(syl):
    v = [letter_code(c) for c in syl]
    return v[0] * 729 + v[1] * 27 + v[2]


# ---- signal allocation ----
_reserved = {CHECK_SIGNAL, "signal-each", "signal-anything", "signal-everything", "signal-any-quality"}
_pool = [s for s in signal_data.raw.keys() if s not in _reserved]
# must be real signal names that exist in the game's catalog - draftsman
# validates against its known signal list, made-up names ("signal-code-0")
# get rejected outright. Slice a big enough pool once and hand out chunks.
WINDOW_CODE_SIGNALS = _pool[:N_WINDOWS]
SYLLABLE_SIGNALS = _pool[N_WINDOWS : N_WINDOWS + 300]
HIDDEN_SIGNALS = _pool[N_WINDOWS + 300 : N_WINDOWS + 300 + len(b1)]
OUTPUT_SIGNALS = _pool[N_WINDOWS + 350 : N_WINDOWS + 350 + len(CLASSES)]

print(f"Syllables: {len(VOCAB)}, hidden: {len(HIDDEN_SIGNALS)}, output: {len(OUTPUT_SIGNALS)}")


def q(x):
    return int(round(x * SCALE))


_BUILD_TAG = "smoke test" if N_SYLLABLES < len(VOCAB_FULL) else "full build"
_OUTPUT_FILE = f"export_full_{N_SYLLABLES}syl.txt"

bp = Blueprint()
bp.label = f"Factorio AI classifier ({_BUILD_TAG}, {N_SYLLABLES} syllables)"
entities = []


def add(e):
    entities.append(e)
    return e


# ---- input row: 50 positions, each its own wire, value 1-27 on CHECK_SIGNAL ----
# TEST_INPUT: bakes VOCAB[0] into positions 1-3 (position 0 stays the
# original "space" placeholder, everything else stays blank) so the
# smoke-test blueprint has a real, falsifiable end-to-end test case
# instead of an all-blank input - lets the whole pipeline (detector ->
# hidden -> output -> 49-condition argmax) be checked against a
# Python-computed expected class, not just "no draftsman warnings".
TEST_INPUT = [None] * INPUT_LEN
TEST_INPUT[0] = 27
if VOCAB:
    for i, ch in enumerate(VOCAB[0]):
        TEST_INPUT[1 + i] = letter_code(ch)

for p in range(INPUT_LEN):
    c = ConstantCombinator(id=f"in_{p}", tile_position=(p * POS_SPACING, 0))
    if TEST_INPUT[p] is not None:
        c.set_signal(index=0, name=CHECK_SIGNAL, count=TEST_INPUT[p])
    add(c)

# ---- window code computation: 3 arithmetic combinators per window, summing
# value(pos)*729 + value(pos+1)*27 + value(pos+2) onto one shared signal ----
CODE_MULT = (729, 27, 1)
code_y = 2  # close to input row - k=2 connections span 4 tiles in x already, keep y small too
for w in range(N_WINDOWS):
    for k in range(3):
        cid = f"code_{w}_{k}"
        add(
            ArithmeticCombinator(
                id=cid,
                tile_position=(w * POS_SPACING, code_y + k * 2),  # 2 apart - arithmetic combinators are 1.3 tall, 1 apart would overlap
                first_operand=CHECK_SIGNAL,
                operation="*",
                second_operand=CODE_MULT[k],
                output_signal=WINDOW_CODE_SIGNALS[w],
            )
        )

for e in entities:
    bp.entities.append(e)

for w in range(N_WINDOWS):
    for k in range(3):
        bp.add_circuit_connection("red", f"in_{w + k}", f"code_{w}_{k}", side_2="input")
    # BUG FOUND 08.08.2026 via in-game numeric verification (not caught by
    # any draftsman warning - it's a missing connection, not a collision):
    # the three code_w_k combinators each correctly compute one term of
    # value*729 + value*27 + value*1, but their OUTPUTS were never wired
    # together - only code_w_2's output ever reached the relay chain, so
    # every window code downstream was just the last term (0-26), never
    # the actual sum. "Summing on a shared wire" (this file's own stated
    # design, see the module docstring) requires the wire to actually
    # exist. Wiring k=0 and k=1's outputs onto k=2's output here merges
    # all three into one network - the relay chain already correctly
    # taps code_w_2's output, so this alone fixes every window.
    bp.add_circuit_connection("red", f"code_{w}_0", f"code_{w}_2", side_1="output", side_2="output")
    bp.add_circuit_connection("red", f"code_{w}_1", f"code_{w}_2", side_1="output", side_2="output")

# ---- per-window relay chain: one independent single-signal pass-through
# chain per window position (NOT one shared bus - keeps codes from
# different windows from ever needing to share a wire, avoids the earlier
# 9-tile-reach problem for the far detector bands) ----
BAND_SIZE = 3  # syllable-detector rows per relay band
n_bands = math.ceil(len(VOCAB) / BAND_SIZE)
relay_base_y = 10  # first hop, 4 above code_w_2's y=6

relay_entities_2 = []
# Each detector fires (window code == this syllable's code) and, instead of
# a plain flag, directly emits its PRECOMPUTED WEIGHT for every hidden
# neuron at once (multi-output decider) - skips a separate 300x32 multiply
# layer entirely. Collapses the remaining problem from "aggregate 300
# syllable signals from across the whole grid" down to "aggregate 32
# hidden-pre signals" - the same signal set regardless of vocabulary size.
detector_entities_2 = []
detectors_in_column = {}  # w -> list of (detector_id, dy) for every detector in that column

for w in range(N_WINDOWS):
    prev_id = f"code_{w}_2"
    for band in range(n_bands):
        ry = relay_base_y + band * RELAY_HOP
        rid = f"relay_{w}_{band}"
        add(
            ArithmeticCombinator(
                id=rid,
                tile_position=(w * POS_SPACING, ry),
                first_operand=WINDOW_CODE_SIGNALS[w],
                operation="*",
                second_operand=1,
                output_signal=WINDOW_CODE_SIGNALS[w],
            )
        )
        relay_entities_2.append((prev_id, rid))
        prev_id = rid

        for row in range(BAND_SIZE):
            s = band * BAND_SIZE + row
            if s >= len(VOCAB):
                break
            dy = ry + (row + 1) * 2
            did = f"det_{s}_{w}"
            add(
                DeciderCombinator(
                    id=did,
                    tile_position=(w * POS_SPACING, dy),
                    conditions=[
                        DeciderCombinator.Condition(
                            first_signal=WINDOW_CODE_SIGNALS[w], comparator="=", constant=window_code(VOCAB[s])
                        )
                    ],
                    outputs=[
                        DeciderCombinator.Output(signal=HIDDEN_SIGNALS[j], copy_count_from_input=False, constant=q(W1[s][j]))
                        for j in range(len(HIDDEN_SIGNALS))
                    ],
                )
            )
            detector_entities_2.append((rid, did))
            detectors_in_column.setdefault(w, []).append((did, dy))

for e in entities[194:]:
    bp.entities.append(e)

for src, dst in relay_entities_2:
    bp.add_circuit_connection("red", src, dst, side_1="output", side_2="input")
for src, dst in detector_entities_2:
    bp.add_circuit_connection("red", src, dst, side_1="output", side_2="input")

# ---- vertical collector per column: merges this column's detector outputs
# going UP (signal-each, since 32 hidden signals coexist without collision)
# so the topmost point per column carries that column's full contribution ----
GREEN = "green"  # separate wire color from the window-code/detector network (red) -
# collector reads detector OUTPUTS (already on red) and re-broadcasts on green,
# keeping the two logical flows (matching vs. accumulating) apart

col_top = {}
new_entities = []
for w in range(N_WINDOWS):
    dets = detectors_in_column.get(w, [])
    if not dets:
        continue
    last_did, last_dy = dets[-1]
    n_hops = math.ceil((last_dy - relay_base_y) / RELAY_HOP) + 1
    prev_id, prev_side = last_did, "output"
    y = last_dy
    hop_positions = []  # (cid, y) - so every other detector in this column can find its nearest hop below
    for hop in range(n_hops):
        y -= RELAY_HOP
        cid = f"colv_{w}_{hop}"
        e = ArithmeticCombinator(id=cid, tile_position=(w * POS_SPACING + 1, max(y, 0)), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
        new_entities.append(e)
        bp.entities.append(e)
        bp.add_circuit_connection(GREEN, prev_id, cid, side_1=prev_side, side_2="input")
        hop_positions.append((cid, max(y, 0)))
        prev_id, prev_side = cid, "output"
    col_top[w] = prev_id

    # BUG FOUND 08.08.2026, same class as the code_w_k summing bug: only
    # the LAST detector created in this column (dets[-1]) ever fed this
    # chain, as its starting input. Every OTHER detector in the same
    # column - including the one that should have fired for the test
    # phrase - computed correctly (confirmed via in-game dump: its
    # condition and outputs were exactly right) but had literally no wire
    # on its output side, so its contribution never reached hidden_pool.
    # Wire every remaining detector to whichever collector hop sits
    # nearest to it in Y (well within the 9-tile wire limit, since hops
    # are RELAY_HOP=8 apart and detector rows are only 2 apart).
    for did, dy in dets[:-1]:
        nearest_cid, _ = min(hop_positions, key=lambda hy: abs(hy[1] - dy))
        bp.add_circuit_connection(GREEN, did, nearest_cid, side_1="output", side_2="input")

# ---- horizontal collector across all 48 columns, chained left to right ----
prev_id = col_top.get(0)
horiz_entities = []
for w in range(1, N_WINDOWS):
    cur_top = col_top.get(w)
    if cur_top is None or prev_id is None:
        continue
    hid = f"colh_{w}"
    e = ArithmeticCombinator(id=hid, tile_position=(w * POS_SPACING, relay_base_y - 2), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    horiz_entities.append(e)
    bp.entities.append(e)
    bp.add_circuit_connection(GREEN, prev_id, hid, side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, cur_top, hid, side_1="output", side_2="input")
    prev_id = hid

last_col_x = (N_WINDOWS - 1) * POS_SPACING
# BUG FOUND 08.08.2026 at full scale (300 syllables), invisible at the 5-
# syllable smoke test: the per-column vertical collector spine (colv_w_hop,
# built above) walks from each column's LAST detector back up toward y=0,
# taking ceil(last_dy/RELAY_HOP) hops - at 100 relay bands (vs 2 in the
# smoke test) that spine is ~800 tiles tall, occupying EVERY column's x
# (w*POS_SPACING+1, i.e. up to last_col_x+1) across that entire y range.
# A margin of +16 put the hidden/output/argmax block's leftward reach
# (its widest cluster - the output layer's snake grid - reaches roughly
# 60 tiles left of final_x) squarely back on top of that spine for a wide
# band of y values, causing hundreds of real OverlappingObjectsWarnings
# that only appear once the spine is tall enough to reach the block's y
# range (needs >~14 bands, i.e. >42 syllables - past the 5-syllable smoke
# test entirely). Fix: push the whole downstream block far enough right
# that even its widest leftward reach clears the spine's x, regardless of
# spine height - a margin comfortably past the minimum, not a tight fit
# (extra bridge hops are cheap, ~1 combinator per 8 tiles).
#
# TIGHTENED 08.08.2026: the first fix used a round +200, which worked (0
# collisions at full scale) but left a wide genuinely-empty strip between
# the detector columns and this block - visibly wasteful in-game (a
# substation lattice still blanketed that empty strip - see the
# near_power_demand fix further down for the other half of this cleanup).
# The block's own widest leftward reach from final_x is the output layer's
# first neuron cluster: neuron_center(0) sits at final_x-49 (NEURON_META_
# SIDE=8, CLUSTER_GAP=14, offset (0-3.5)*14=-49), plus ~6 tiles of the
# cluster's own grid+bias extent = ~55 tiles. Needs to clear last_col_x+1
# (the spine's own max x) with margin: last_col_x + margin - 55 > last_col_x
# + 1, i.e. margin > 56. +100 leaves a comfortable ~40-tile buffer over
# that minimum - still generous, but half the previous gap.
bridge_target_x = last_col_x + 100
n_bridge_hops = math.ceil((bridge_target_x - last_col_x) / RELAY_HOP)
bx = last_col_x
for hop in range(n_bridge_hops):
    bx = min(bx + RELAY_HOP, bridge_target_x)
    bid = f"bridge_{hop}"
    e = ArithmeticCombinator(id=bid, tile_position=(bx, relay_base_y - 2), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(e)
    bp.add_circuit_connection(GREEN, prev_id, bid, side_1="output", side_2="input")
    prev_id = bid

# one more hop straight down into clean empty space, well clear of the
# horizontal bridge row itself - avoids the hidden-layer cluster overlapping
# the very entities that feed it
drop_id = "bridge_drop"
drop_y = (relay_base_y - 2) + RELAY_HOP
e = ArithmeticCombinator(id=drop_id, tile_position=(bridge_target_x, drop_y), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(e)
bp.add_circuit_connection(GREEN, prev_id, drop_id, side_1="output", side_2="input")
prev_id = drop_id

FINAL_HIDDEN_SUM = prev_id  # entity id carrying the fully-collected 32 hidden-pre signals
print(f"Final collection point: {FINAL_HIDDEN_SUM}")

# ---- hidden layer bias + ReLU, clustered around the drop point, clear of
# every other entity in the design ----
final_x = bridge_target_x
final_y = drop_y
# Grid uses an EVEN side count with spacing 1.4 (just above a combinator's
# 1.3-tile max dimension) and offsets symmetric around 0 - e.g. for side=6:
# -3.5,-2.1,-0.7,0.7,2.1,3.5. With an even count, 0 always falls in the GAP
# between the two middle cells, never on a cell itself - so (final_x,
# final_y) is guaranteed empty and safe for the collection point. bias_id
# goes just outside the grid's corner (radius ~5, clear of every cell).
GRID_SPACING = 2  # fractional spacing (tried 1.4) gets snapped unpredictably by
# draftsman/the game's placement grid - integer spacing has been reliable
# throughout this whole project, stick with what's proven
grid_side = math.ceil(math.sqrt(len(HIDDEN_SIGNALS)))
if grid_side % 2:
    grid_side += 1


def grid_offset(i):
    return (i - (grid_side - 1) / 2) * GRID_SPACING


bias_id = "hidden_bias"
bias_c = ConstantCombinator(id=bias_id, tile_position=(final_x + 5, final_y + 5))
for j in range(len(HIDDEN_SIGNALS)):
    bias_c.set_signal(index=j, name=HIDDEN_SIGNALS[j], count=q(b1[j]))
bp.entities.append(bias_c)
bp.add_circuit_connection(GREEN, bias_id, FINAL_HIDDEN_SUM, side_2="input")

relu_ids = []
for j in range(len(HIDDEN_SIGNALS)):
    gx, gy = j % grid_side, j // grid_side
    rid = f"hrelu_{j}"
    e = DeciderCombinator(
        id=rid,
        tile_position=(final_x + grid_offset(gx), final_y + grid_offset(gy)),
        conditions=[DeciderCombinator.Condition(first_signal=HIDDEN_SIGNALS[j], comparator=">=", constant=0)],
        outputs=[DeciderCombinator.Output(signal=HIDDEN_SIGNALS[j], copy_count_from_input=True)],
    )
    bp.entities.append(e)
    bp.add_circuit_connection(GREEN, FINAL_HIDDEN_SUM, rid, side_1="output", side_2="input")
    relu_ids.append(rid)

print(f"Hidden layer done: bias + {len(relu_ids)} ReLU deciders")

# ---- collect all 32 post-ReLU hidden signals into one point, so the output
# layer can read them from a single nearby location instead of reaching
# into 32 different grid cells individually. x-offset 0 is never used by any
# grid cell (offsets are always in {-5,-3,-1,1,3,5}), so x=final_x+1.5 (near
# 0, clearly distinct from drop_id which sits exactly at the true center)
# is guaranteed clear, and stays within reach of the whole +-5 grid ----
RED2 = "red"  # different logical network from the GREEN pre-activation bus, safe to reuse the name
hidden_pool_id = "hidden_pool"
e = ArithmeticCombinator(id=hidden_pool_id, tile_position=(final_x, final_y + 2), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(e)
for rid in relu_ids:
    bp.add_circuit_connection(RED2, rid, hidden_pool_id, side_1="output", side_2="input")

print(f"Hidden pool collected at: {hidden_pool_id}")

# ---- reusable helpers (see PROJECT.md Decision 8: hand-computing x/y for
# every new bridge/cluster stopped scaling once inter-cluster wiring was
# the thing being built, not just cluster interiors - these two replace
# that with a point-to-point bridge and a proven-safe cluster placer) ----
_bridge_counter = 0


def bridge(from_id, from_pos, to_pos, wire_color, hop=RELAY_HOP):
    """
    Chain of signal-each relay combinators connecting from_id (physically
    at from_pos) to a fresh point at to_pos, each hop <= `hop` tiles
    (under the 9-tile wire limit), landing exactly on to_pos with no
    leftover fractional step. Returns (last_id, last_pos) to keep
    chaining from, or to wire one final direct connection into/from an
    existing entity.

    This only guarantees hops are correctly spaced along the from->to
    line - it does NOT check the line is clear of other entities. Callers
    route around known-occupied regions (e.g. a cluster's own footprint)
    by picking a from/to pair that stays outside it - e.g. by only ever
    moving along a cluster's own zero-offset row/column (see
    neuron_center below), which grid cells never use.
    """
    global _bridge_counter
    fx, fy = from_pos
    tx, ty = to_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist < 1e-9:
        return from_id, from_pos
    n_hops = max(1, math.ceil(dist / hop))
    prev_id, prev_pos = from_id, from_pos
    for h in range(1, n_hops + 1):
        t = h / n_hops
        pos = (fx + (tx - fx) * t, fy + (ty - fy) * t)
        _bridge_counter += 1
        bid = f"gbridge_{_bridge_counter}"
        e = ArithmeticCombinator(id=bid, tile_position=pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
        bp.entities.append(e)
        bp.add_circuit_connection(wire_color, prev_id, bid, side_1="output", side_2="input")
        prev_id, prev_pos = bid, pos
    return prev_id, prev_pos


_cluster_counter = 0


def place_cluster_and_connect(center, n, build_fn, remote_source_id, wire_color, spacing=2, collect=True):
    """
    Places n entities around `center` using the proven safe layout (even
    side count, integer spacing -> cell offsets are always odd multiples
    of spacing, so `center` itself is guaranteed empty - see PROJECT.md
    "empty center of an even grid"). Wires remote_source_id's output
    directly to every placed entity's input (one broadcast source, n
    listeners - cell-specific behavior comes from each entity's own
    parameters via build_fn, not from distinct wiring).

    Caller's responsibility: keep n small enough that the grid's corner
    stays within the 9-tile wire limit of `center` (n<=36 at spacing=2 is
    the proven-safe budget used throughout this file, corner distance
    ~7.1 tiles) - for bigger clusters, call this multiple times on
    sub-chunks, bridging center-to-center between chunks.

    build_fn(i, pos) -> Entity must construct and return entity i already
    carrying its own id and tile_position=pos.

    If collect=True, also places ONE more arithmetic combinator gathering
    every placed entity's output via signal-each, and returns its
    (id, pos) as the second tuple element (None if collect=False, e.g.
    argmax, where each cell's output is its own distinctly-named signal
    with nothing further to sum locally). The collector sits at
    (center_x, center_y + 2), NOT exactly at center - center itself is
    where an incoming broadcast source (e.g. a bridge()'s last hop) is
    expected to land, and x-offset 0 is never used by any grid cell
    (offsets are always odd multiples of spacing), so any (center_x, y)
    is safe regardless of y - same reasoning already used for ocol_id
    earlier in this file.
    """
    global _cluster_counter
    cx, cy = center
    side = math.ceil(math.sqrt(n))
    if side % 2:
        side += 1

    def offset(i):
        return (i - (side - 1) / 2) * spacing

    ids = []
    for i in range(n):
        gx, gy = i % side, i // side
        pos = (cx + offset(gx), cy + offset(gy))
        e = build_fn(i, pos)
        bp.entities.append(e)
        ids.append(e.id)
        if remote_source_id is not None:
            bp.add_circuit_connection(wire_color, remote_source_id, e.id, side_1="output", side_2="input")

    if not collect:
        return ids, None

    _cluster_counter += 1
    collector_id = f"cluster_collect_{_cluster_counter}"
    collector_pos = (cx, cy + 2)
    collector = ArithmeticCombinator(id=collector_id, tile_position=collector_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(collector)
    for eid in ids:
        bp.add_circuit_connection(wire_color, eid, collector_id, side_1="output", side_2="input")
    return ids, (collector_id, collector_pos)


# ---- output layer: 50 topic neurons, same relay-chain-plus-local-cluster
# pattern as the syllable detectors - one relay hop per neuron, each
# serving a 32-cell multiply cluster (hidden_j * W2[j][k]) around it.
# SAME square 6x6 (36-cell, 32 used) layout that already worked cleanly for
# the ReLU grid: spacing 2, EVEN side count so offsets are always odd
# ({-5,-3,-1,1,3,5}) and the true center (0,0) is guaranteed empty - no
# need to reinvent this per grid, just reuse the exact working recipe.
OUT_GRID_SIDE = math.ceil(math.sqrt(len(HIDDEN_SIGNALS)))
if OUT_GRID_SIDE % 2:
    OUT_GRID_SIDE += 1


def out_offset(i):
    return (i - (OUT_GRID_SIDE - 1) / 2) * 2


CLUSTER_GAP = (OUT_GRID_SIDE - 1) * 2 + 4  # grid span + margin, e.g. 10+4=14 for side=6

# 50 neuron clusters used to stack in one straight vertical column
# (50 * CLUSTER_GAP = 700 tiles tall for just this layer alone) - a long
# thin strip that doesn't fit well on a real map and isn't required by the
# math (nothing here needs a line). Arranged instead as a 2D "snake" grid:
# neuron k+1 is always physically adjacent to neuron k (same row, next
# column - or at a row's end, same column, next row down), so consecutive
# relay/collection hops stay exactly CLUSTER_GAP apart, same as before,
# without ever needing a long-distance corridor to a far-off column.
NEURON_META_SIDE = math.ceil(math.sqrt(len(OUTPUT_SIGNALS)))
if NEURON_META_SIDE % 2:
    NEURON_META_SIDE += 1


def neuron_center(k):
    row, col = divmod(k, NEURON_META_SIDE)
    if row % 2:  # odd rows walk right-to-left, so k -> k+1 is always one step, never a jump across the row
        col = NEURON_META_SIDE - 1 - col
    cx = final_x + (col - (NEURON_META_SIDE - 1) / 2) * CLUSTER_GAP  # centered in X, like everything else anchored on final_x
    cy = out_relay_y + row * CLUSTER_GAP  # grows downward only, never back up into the ReLU grid above
    return (cx, cy)


out_prev = hidden_pool_id
out_prev_pos = (final_x, final_y + 2)  # hidden_pool's own position
out_relay_y = final_y + 20  # clear gap below the relu grid (which spans final_y +-5)
output_signal_of = {}
output_pos_of = {}
for k in range(len(OUTPUT_SIGNALS)):
    cx, cy = neuron_center(k)
    # bridge from wherever we left off to this neuron's true center - lands
    # exactly there and becomes this neuron's local relay hop (safe: (0,0)
    # relative to ANY cluster is never a grid cell, and nothing else has
    # been placed at this exact point yet)
    out_prev, out_prev_pos = bridge(out_prev, out_prev_pos, (cx, cy), RED2, hop=RELAY_HOP)

    mult_ids = []
    for j in range(len(HIDDEN_SIGNALS)):
        gx, gy = j % OUT_GRID_SIDE, j // OUT_GRID_SIDE
        mid = f"omul_{k}_{j}"
        e = ArithmeticCombinator(
            id=mid,
            tile_position=(cx + out_offset(gx), cy + out_offset(gy)),
            first_operand=HIDDEN_SIGNALS[j],
            operation="*",
            second_operand=q(W2[j][k]),
            output_signal=OUTPUT_SIGNALS[k],
        )
        bp.entities.append(e)
        bp.add_circuit_connection(RED2, out_prev, mid, side_1="output", side_2="input")
        mult_ids.append(mid)

    # bias: only needs to reach ocol_id (one connection), so the safe corner
    # offset (5,5) works fine here - same corner proven empty for the ReLU
    # grid's bias (only 32 of 36 cells used, last row fills just gx=0,1)
    bias_oid = f"obias_{k}"
    e = ConstantCombinator(id=bias_oid, tile_position=(cx + 5, cy + 5))
    e.set_signal(index=0, name=OUTPUT_SIGNALS[k], count=q(b2[k]))
    bp.entities.append(e)

    # ocol_id is different: it must reach ALL 32 scattered mult_ids, so it
    # needs to stay near the true CENTER (corner offset was wrong here -
    # that's what caused the >9-tile distance warnings to the far cells).
    # x=0 offset is never used by any grid cell (offsets are always odd:
    # +-1,+-3,+-5), so any (0, y) is safe regardless of y - y=+2 clears the
    # local relay hop sitting exactly at (0,0) without leaving the center
    ocol_id = f"ocol_{k}"
    e = ArithmeticCombinator(id=ocol_id, tile_position=(cx, cy + 2), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(e)
    bp.add_circuit_connection(RED2, bias_oid, ocol_id, side_2="input")
    for mid in mult_ids:
        bp.add_circuit_connection(RED2, mid, ocol_id, side_1="output", side_2="input")
    output_signal_of[k] = ocol_id
    output_pos_of[k] = (cx, cy)

print(f"Output layer done: {len(OUTPUT_SIGNALS)} neurons")

# ---- collect all 50 output-class signals into one point for argmax.
# Neuron k+1 sits right next to neuron k (see neuron_center's snake
# order), so this walks the SAME short adjacent-cluster hops as the feed
# chain above, instead of needing a dedicated far-away corridor. Each
# hop's waypoint sits at (center_x, center_y + 4) - x=center_x (offset 0)
# is never a used grid-cell x-offset for ANY cluster, so travel at that x
# is safe regardless of y (same reasoning as ocol_id's own x=0 choice) -
# +4 just keeps this waypoint from landing exactly on the two OTHER
# points already sitting at this same safe column (the feed-chain relay
# at +0, ocol_id at +2). No extra merge entity needed either: ocol_k's
# value is wired straight into the waypoint bridge() just created -
# Factorio sums same-named signals from multiple input wires for free ----
all_out_prev, all_out_pos = output_signal_of[0], output_pos_of[0]
for k in range(1, len(OUTPUT_SIGNALS)):
    cx, cy = output_pos_of[k]
    all_out_prev, all_out_pos = bridge(all_out_prev, all_out_pos, (cx, cy + 4), RED2, hop=RELAY_HOP)
    bp.add_circuit_connection(RED2, output_signal_of[k], all_out_prev, side_1="output", side_2="input")

ALL_OUTPUTS = all_out_prev
print(f"All 50 output signals collected at: {ALL_OUTPUTS}")

CORRIDOR_X = final_x + int(abs(out_offset(0))) + 1

# ---- argmax: 50-way winner-take-all via pairwise comparison (pattern
# proven at n=3 in demo_export.py - one decider per class with N-1 AND'd
# conditions comparing its own score against every other class, >= for
# lower indices so an exact tie breaks toward the first index, > for
# higher indices so exactly one decider ever fires). All conditions read
# from the SAME broadcast wire (ALL_OUTPUTS already carries all 50 named
# signals at once) - one connection per decider, not one per condition.
# NOTE: only ever proven in-game at n=3/2-conditions (demo); the 49-AND
# condition list here is architecturally the same feature but untested at
# this width - worth a real in-game check before trusting it blindly.
#
# 50 doesn't fit in a single safe cluster radius (a square grid needs
# side 8 to hold 50 cells, and its corner distance at spacing=2 is ~9.9
# tiles - over the wire limit) - split into 2 chunks of 25 (side 6, corner
# distance ~7.1 tiles, the same margin the hidden/output layers already
# rely on) and bridge the broadcast signal from one chunk's center to the
# next, same as everywhere else in this file ----
WINNER_SIGNALS = _pool[N_WINDOWS + 350 + len(CLASSES) : N_WINDOWS + 350 + 2 * len(CLASSES)]


def build_argmax(k, pos):
    conditions = []
    for other in range(len(OUTPUT_SIGNALS)):
        if other == k:
            continue
        comparator = ">=" if other > k else ">"
        conditions.append(
            DeciderCombinator.Condition(
                first_signal=OUTPUT_SIGNALS[k], comparator=comparator, second_signal=OUTPUT_SIGNALS[other], compare_type="and"
            )
        )
    return DeciderCombinator(
        id=f"argmax_{k}",
        tile_position=pos,
        conditions=conditions,
        outputs=[DeciderCombinator.Output(signal=WINNER_SIGNALS[k], copy_count_from_input=False, constant=1)],
    )


ARGMAX_CHUNK = 25
argmax_source, argmax_pos = ALL_OUTPUTS, all_out_pos
argmax_ids = []
chunk_collectors = []
for c in range(math.ceil(len(OUTPUT_SIGNALS) / ARGMAX_CHUNK)):
    lo = c * ARGMAX_CHUNK
    hi = min(lo + ARGMAX_CHUNK, len(OUTPUT_SIGNALS))
    center = (final_x, all_out_pos[1] + 20 + c * 20)
    argmax_source, argmax_pos = bridge(argmax_source, argmax_pos, center, RED2, hop=RELAY_HOP)
    # collect=True here (unlike a plain flag cluster) isn't for summing -
    # each decider's WINNER_SIGNAL is uniquely named so signal-each just
    # passes them all through untouched - it's to give every argmax
    # decider a real consumer on its output side. Without one, a
    # script-based signal dump reads empty regardless of whether the
    # decider computed correctly (the exact "terminal node, no wire on
    # that side" gotcha from PROJECT.md Решение 5 that cost hours before).
    ids, (chunk_collector_id, chunk_collector_pos) = place_cluster_and_connect(
        center, hi - lo, lambda i, pos, lo=lo: build_argmax(lo + i, pos), argmax_source, RED2, collect=True
    )
    argmax_ids.extend(ids)
    chunk_collectors.append((chunk_collector_id, chunk_collector_pos))

# merge the per-chunk collectors into one final point carrying all 50
# WINNER_SIGNALS at once - same corridor-bridge pattern as ALL_OUTPUTS
# above, and doubles as the future Display Panel's input point
CORRIDOR_DX2 = CORRIDOR_X - final_x
argmax_prev, argmax_prev_pos = chunk_collectors[0]
argmax_prev, argmax_prev_pos = bridge(argmax_prev, argmax_prev_pos, (argmax_prev_pos[0] + CORRIDOR_DX2, argmax_prev_pos[1]), RED2, hop=RELAY_HOP)
for cid, cpos in chunk_collectors[1:]:
    corridor_pos = (cpos[0] + CORRIDOR_DX2, cpos[1])
    argmax_prev, argmax_prev_pos = bridge(argmax_prev, argmax_prev_pos, corridor_pos, RED2, hop=RELAY_HOP)
    merge_id = f"argmax_merge_{cid}"
    e = ArithmeticCombinator(id=merge_id, tile_position=(corridor_pos[0] + 1, corridor_pos[1]), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(e)
    bp.add_circuit_connection(RED2, argmax_prev, merge_id, side_1="output", side_2="input")
    bp.add_circuit_connection(RED2, cid, merge_id, side_1="output", side_2="input")
    argmax_prev, argmax_prev_pos = merge_id, (corridor_pos[0] + 1, corridor_pos[1])

ARGMAX_RESULT = argmax_prev
print(f"Argmax result (all winner signals) collected at: {ARGMAX_RESULT}")

print(f"Argmax done: {len(argmax_ids)} deciders")

# ---- output: Display Panel, native 2.0 mechanic (up to 100 signal-condition
# -> text+icon pairs, checked top to bottom) - no combinators needed, see
# PROJECT.md Decision 2. Each of the 50 WINNER_SIGNALS is exactly 1 for the
# winning class and simply ABSENT (not 0) for every other class - argmax's
# winner-take-all guarantees exactly one match, so a plain "signal = 1" per
# class is enough and message order doesn't matter (never two matches at
# once). Placed a short direct hop from ARGMAX_RESULT - well under the
# 9-tile wire limit, no bridge() needed for a single terminal connection.
panel_pos = (argmax_prev_pos[0] + 2, argmax_prev_pos[1])
display_panel = DisplayPanel(
    id="display_panel",
    tile_position=panel_pos,
    messages=[
        DisplayPanel.Message(text=CLASS_RESPONSES[k], condition=Condition(first_signal=WINNER_SIGNALS[k], comparator="=", constant=1))
        for k in range(len(CLASSES))
    ],
)
bp.entities.append(display_panel)
bp.add_circuit_connection(RED2, ARGMAX_RESULT, "display_panel", side_1="output")

print(f"Display Panel done: {len(CLASSES)} class -> response messages")

# ---- power: substation lattice covering the whole build, 12-tile spacing
# (supply_area_distance=9 gives generous overlap between neighbors, wire
# reach=18 comfortably covers the ~17-tile diagonal) - the exact pattern
# already proven at 5000+ combinator scale in stress_test_wired_export.py.
# Constant combinators don't need power; every arithmetic/decider
# combinator here does (confirmed the hard way in demo_export.py) - this
# was missing entirely until now, an oversight draftsman never flags
# (it doesn't validate power at all, only physical/wire placement).
#
# UNLIKE the stress test, this build's own combinator layout wasn't
# designed around the lattice (the lattice is retrofitted onto an already-
# packed design), so a naive 12-tile grid lands squarely on top of dense
# regions (the input row, detector bands). Each candidate point is nudged
# to the nearest free spot (spiral search, small bucketed occupancy index
# instead of an O(n) scan per candidate - this runs against 2000+
# entities) rather than hand-picking clear coordinates per region.
SUB_SPACING = 12


def pos_of(e):
    # .position (the true float center draftsman uses for collision math),
    # NOT .tile_position (a grid-cell reference that gets silently rounded
    # AND is offset from the true center by an entity-size-dependent amount
    # - e.g. decider/arithmetic combinators sit at tile_position+(0.5,1.0),
    # constant combinators and medium-electric-pole at +(0.5,0.5),
    # substation at +(1.0,1.0). Comparing raw tile_position values across
    # different entity TYPES - as this whole power section originally did
    # - silently compares the wrong points. Confirmed empirically: this
    # was the actual root cause of several rounds of "the math says this
    # should be free" collisions here, not a spacing/threshold error.
    p = e.position
    return (p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1])


powered_types = {"arithmetic-combinator", "decider-combinator"}
entities_needing_power = [(e, pos_of(e)) for e in bp.entities if e.name in powered_types]

# WASTE FOUND 08.08.2026 (spotted by eye in-game, not by any automated
# check): the substation lattice below rasterizes the ENTIRE bounding
# rectangle of the build at a fixed 12-tile spacing, with no notion of
# whether anything is actually THERE to power. That's harmless when the
# layout roughly fills its own bounding box, but Bug 1's fix above (Решение
# 11) pushed the hidden/output/argmax block ~200 tiles sideways from the
# detector columns to dodge the tall vertical-collector spine - leaving a
# wide genuinely-empty strip in between that the lattice still blankets
# with substations, none of which have anything nearby to supply. Fix:
# skip a lattice CANDIDATE point outright (don't even try find_free_spot
# for it) if no powered entity exists within reach of it - gap-fill below
# already exists specifically to patch any resulting coverage holes near
# real entities, using the same nearest-source-distance logic either way,
# so this doesn't reduce correctness, only how many pre-seeded lattice
# points get tried in territory nothing will ever use.
_DEMAND_BUCKET = 8
_demand_bucket = {}
for _e, (_ex, _ey) in entities_needing_power:
    _key = (int(_ex // _DEMAND_BUCKET), int(_ey // _DEMAND_BUCKET))
    _demand_bucket.setdefault(_key, []).append((_ex, _ey))


def near_power_demand(x, y, radius=10):
    kx, ky = int(x // _DEMAND_BUCKET), int(y // _DEMAND_BUCKET)
    span = math.ceil(radius / _DEMAND_BUCKET) + 1
    for bx in range(kx - span, kx + span + 1):
        for by in range(ky - span, ky + span + 1):
            for ex, ey in _demand_bucket.get((bx, by), ()):
                if math.hypot(ex - x, ey - y) <= radius:
                    return True
    return False


BUCKET = 2
occupied_bucket = {}
for e in bp.entities:
    px, py = pos_of(e)
    key = (int(px // BUCKET), int(py // BUCKET))
    occupied_bucket.setdefault(key, []).append((px, py))


# Collision boxes here are all narrow: substation 0.7x0.7, arithmetic/
# decider combinators ~0.7x1.3 (per demo_export.py's own measurement). A
# UNIFORM threshold on both axes (tried 1.6 first) is wrong: it forbids
# the X-diff=1 placements this whole file already relies on elsewhere
# (e.g. the CORRIDOR_X+1 merge trick) even though half-widths (0.35+0.35)
# only need ~0.7-1.0 separation in X - only Y needs the bigger margin
# (half-heights 0.65+0.35 need ~1.0-1.3). That mismatch was silently
# rejecting real free spots (like the 1-tile gap next to a detector
# column) and was the actual reason gap-fill couldn't find anywhere to
# place a substation in the densest region, not genuine total density.
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
    """Full ring scan (every cell at Chebyshev distance r, not just the 8
    compass points) so a genuinely free spot close by is never skipped
    past in favor of a farther, coincidentally-checked one. Returns None
    (caller should skip this lattice point, NOT fall back to the original
    colliding position - that was the actual bug behind an earlier round
    of warnings here) if nothing opens up within max_radius."""
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


xs_all = [pos_of(e)[0] for e in bp.entities]
ys_all = [pos_of(e)[1] for e in bp.entities]
min_x, max_x = min(xs_all), max(xs_all)
min_y, max_y = min(ys_all), max(ys_all)
n_cols = math.ceil((max_x - min_x) / SUB_SPACING) + 1
n_rows = math.ceil((max_y - min_y) / SUB_SPACING) + 1

sub_lattice = {}
sub_positions = {}
nudged = 0
skipped = 0
empty_skipped = 0
for r in range(n_rows):
    for c in range(n_cols):
        sx, sy = min_x + c * SUB_SPACING, min_y + r * SUB_SPACING
        # radius here is deliberately generous (lattice spacing 12 + reach 9,
        # rounded up) - the goal is only to skip points sitting in genuinely
        # empty territory (hundreds of tiles wide), not to finely optimize
        # coverage; gap-fill below still finds and covers anything real that
        # ends up under-covered, same as it always has.
        if not near_power_demand(sx, sy, radius=20):
            empty_skipped += 1
            continue
        spot = find_free_spot(sx, sy)
        if spot is None:
            skipped += 1
            continue
        fx, fy = spot
        if (fx, fy) != (sx, sy):
            nudged += 1
        sub_id = f"sub_{r}_{c}"
        bp.entities.append(ElectricPole(name="substation", id=sub_id, position=(fx, fy), quality="legendary"))
        mark_occupied(fx, fy)  # so the NEXT lattice point's search can't land on this one
        sub_lattice[(r, c)] = sub_id
        sub_positions[(r, c)] = (fx, fy)

# BUG FOUND 08.08.2026 via in-game/draftsman ConnectionDistanceWarning:
# find_free_spot's nudging (above) moves each lattice point independently
# to dodge collisions, with no awareness of how far that pushes it from
# its wire-linked neighbors - two adjacent points nudged apart from each
# other can end up past a substation's 18-tile max_wire_distance (observed:
# 18.97 tiles at just N_SYLLABLES=25, where nudging is already common in
# the denser detector-column region). Fix: check actual distance before
# linking, and thread relay poles (9-tile pole reach, RELAY_HOP=8 margin,
# same pattern as power_bridge below) through any link that's come up
# short, instead of assuming the base 12-tile lattice spacing always
# survives nudging intact.
sub_links = 0
_sub_link_relay_counter = 0
_sub_link_relays = []  # (id, x, y, radius) - folded into the power coverage cache below, once it exists
for (r, c), sub_id in sub_lattice.items():
    pos_a = sub_positions[(r, c)]
    for nr, nc in ((r, c + 1), (r + 1, c)):
        neighbor_id = sub_lattice.get((nr, nc))
        if neighbor_id is None:
            continue
        pos_b = sub_positions[(nr, nc)]
        dist = math.hypot(pos_b[0] - pos_a[0], pos_b[1] - pos_a[1])
        if dist <= 17:  # 1-tile safety margin under the true 18-tile limit
            bp.add_power_connection(sub_id, neighbor_id)
        else:
            n_hops = math.ceil(dist / 8)
            prev_id, prev_pos = sub_id, pos_a
            for h in range(1, n_hops):
                t = h / n_hops
                target = (pos_a[0] + (pos_b[0] - pos_a[0]) * t, pos_a[1] + (pos_b[1] - pos_a[1]) * t)
                spot = find_free_spot(*target, max_radius=4, min_dist_x=0.55, min_dist_y=0.85) or target
                _sub_link_relay_counter += 1
                rid = f"sub_link_relay_{_sub_link_relay_counter}"
                bp.entities.append(ElectricPole(name="medium-electric-pole", id=rid, position=spot, quality="legendary"))
                mark_occupied(*spot)
                bp.add_power_connection(prev_id, rid)
                _sub_link_relays.append((rid, spot[0], spot[1], 3.5))
                prev_id, prev_pos = rid, spot
            bp.add_power_connection(prev_id, neighbor_id)
        sub_links += 1

# ---- gap-fill pass: the lattice above is a rigid 12-tile grid retrofitted
# onto an already-dense layout, so some points got skipped entirely (no
# free spot within reach - e.g. the detector/relay columns are packed
# solid enough in places that NO point clears a substation's own
# footprint). A skipped lattice point can leave real coverage holes
# (measured, not assumed - a first pass left one arithmetic combinator
# 13.4 tiles from its nearest substation, over the 9-tile supply_area_
# distance limit). Instead of reasoning about exactly which regions are
# too dense by hand, just measure the actual worst-covered entity and
# drop one more substation next to it, repeat until every entity needing
# power is within reach or a sane iteration cap is hit.
# (powered_types / entities_needing_power are already computed further up,
# alongside the demand index used to sparsify the lattice above)

# PERFORMANCE BUG FOUND 08.08.2026 via cProfile (see PROJECT.md): the
# original worst_covered() rescanned EVERY powered entity against EVERY
# power source, from scratch, on EVERY gap-fill iteration below - O(
# iterations * entities * len(power_net)). At N_SYLLABLES=25 (a small
# fraction of the full 300) that was already 524 MILLION math.hypot calls,
# 972 of a 1140-second total run (85%) - and BOTH factors in that product
# grow with N_SYLLABLES, so real full-scale runs were headed for hours,
# not minutes. A single entity's power_net membership doesn't change
# between iterations - only ONE new source gets added per iteration - so
# there's no need to recheck old sources at all: cache each entity's best-
# so-far (nearest source distance - that source's radius), and when a new
# source is added, fold just THAT source into the cache in one O(entities)
# pass instead of redoing the full O(entities * power_net) scan. Iteration
# count and entity count are unchanged (same gap-fill behavior/output),
# only the redundant rework is gone.
_slack_of = {}  # id(e) -> current best (nearest source distance - its radius)
power_net = []  # every currently-connected power entity, as (id, x, y, supply_area_distance)


def _register_power_source(entry):
    """Adds `entry` (id, x, y, radius) to power_net and folds it into every
    powered entity's slack cache in one O(entities) pass (not O(entities *
    power_net) - see perf note above). Returns (worst_slack, worst_pos)
    over ALL entities and ALL sources registered so far - the entity
    farthest OUTSIDE every power source's own supply_area_distance (not
    just farthest from the nearest source's CENTER - a small pole's 3.5-
    tile reach and a substation's 9-tile reach aren't comparable by raw
    distance alone)."""
    power_net.append(entry)
    _, nx, ny, nr = entry
    worst_slack, worst_pos = -1e9, None
    for e, (ex, ey) in entities_needing_power:
        d = math.hypot(ex - nx, ey - ny) - nr
        key = id(e)
        cur = _slack_of.get(key, 1e18)
        if d < cur:
            cur = d
            _slack_of[key] = cur
        if cur > worst_slack:
            worst_slack, worst_pos = cur, (ex, ey)
    return worst_slack, worst_pos


def nearest_power(fx, fy):
    return min(power_net, key=lambda t: math.hypot(t[1] - fx, t[2] - fy))


# bulk-fold the initial substation lattice (and any sub_link_relay poles
# threaded through overlong links above) into the cache once
worst_slack, worst_pos = -1e9, None
for sid, (sx, sy) in ((sub_lattice[k], sub_positions[k]) for k in sub_lattice):
    worst_slack, worst_pos = _register_power_source((sid, sx, sy, 9))
for entry in _sub_link_relays:
    worst_slack, worst_pos = _register_power_source(entry)

# Pass 1: substations (9-tile reach) - covers everything with room for one.
# Iteration caps (here and pass 2 below) were sized for the 5/25/60-syllable
# test scales - at the full 300-syllable scale the substation lattice skips
# far more points (462 vs 91 at N=60, since the detector-column region is
# both denser AND much taller), so pass 2 needs far more poles to patch it
# all. BUG FOUND 08.08.2026: the first full-scale run hit pass 2's old cap
# of 400 poles before worst_slack reached 0 (ended at 4.12 tiles of real
# uncovered slack - a genuine "no power" spot in-game, not just a
# theoretical shortfall) - caught by reading the run's own printed summary,
# not a draftsman warning (draftsman doesn't know about our power-slack
# bookkeeping at all). Raised generously now that each iteration is cheap
# (the O(n^2) perf fix above, not O(1), but O(entities) per iteration -
# a few thousand extra iterations costs seconds, not the ~24 minutes the
# whole build already takes).
gap_fill_count = 0
for _ in range(500):
    if worst_slack <= 0:
        break
    # search radius must stay < supply_area_distance (9) - a free spot
    # found FARTHER than that from worst_pos wouldn't actually cover it,
    # even though find_free_spot would happily return it as "free" (this
    # was the actual bug behind an earlier gap-fill attempt topping out
    # at 12.00 tiles instead of converging: it searched radius 12, found
    # real free spots, just too far away to fix anything)
    spot = find_free_spot(*worst_pos, max_radius=8)
    if spot is None:
        break  # no room for a SUBSTATION here - pass 2 below handles this with a smaller pole instead
    fx, fy = spot
    gap_fill_count += 1
    sub_id = f"sub_gap_{gap_fill_count}"
    bp.entities.append(ElectricPole(name="substation", id=sub_id, position=(fx, fy), quality="legendary"))
    mark_occupied(fx, fy)
    nearest_id = nearest_power(fx, fy)[0]
    bp.add_power_connection(sub_id, nearest_id)
    worst_slack, worst_pos = _register_power_source((sub_id, fx, fy, 9))

# Pass 2: medium electric poles (collision_box half-width/height 0.15,
# supply_area_distance 3.5, max_wire_distance 9) for whatever's left -
# substations (half-width/height 0.7) genuinely don't fit between columns
# spaced POS_SPACING=2 apart (needs >=1.05 clearance, the gap only offers
# 1.0), confirmed empirically, not assumed. A pole's tiny footprint
# (needs ~0.5/0.8 clearance) fits the same 1-tile gaps with room to spare.
#
# A gap-fill pole sits, by construction, in the hardest-to-reach spot near
# the worst-covered entity - which means the nearest EXISTING power node is
# often farther than the pole's own 9-tile max_wire_distance. A first
# version silently skipped the power_connection in that case (kept "if
# within 9" and did nothing otherwise) - the pole still covered its
# target entity in this script's own bookkeeping (power_net), but had NO
# actual power itself, so it couldn't relay any. Confirmed in-game (not
# just suspected): the player saw a real "no power" block matching this
# exactly, and a wire-graph BFS from the power source over the actual
# blueprint data showed 49 of 54 gap-fill poles were disconnected
# islands - every one of them past the 9-tile mark. Fixed with a
# power-side relay chain (power_bridge below), the same "hop <= reach,
# find a free spot for each intermediate link" idea as the circuit-side
# bridge() used everywhere else in this file, just for copper wire.
_power_relay_counter = 0


def power_bridge(from_id, from_pos, to_pos):
    fx, fy = from_pos
    tx, ty = to_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist <= 9:
        return from_id, from_pos
    global _power_relay_counter
    n_hops = math.ceil(dist / 8)  # slightly under the 9-tile max_wire_distance, for margin
    prev_id, prev_pos = from_id, from_pos
    for h in range(1, n_hops + 1):
        t = h / n_hops
        target = (fx + (tx - fx) * t, fy + (ty - fy) * t)
        spot = find_free_spot(*target, max_radius=4, min_dist_x=0.55, min_dist_y=0.85) or target
        _power_relay_counter += 1
        rid = f"power_relay_{_power_relay_counter}"
        bp.entities.append(ElectricPole(name="medium-electric-pole", id=rid, position=spot, quality="legendary"))
        mark_occupied(*spot)
        bp.add_power_connection(prev_id, rid)
        _register_power_source((rid, spot[0], spot[1], 3.5))
        prev_id, prev_pos = rid, spot
    return prev_id, prev_pos


pole_fill_count = 0
for _ in range(4000):
    if worst_slack <= 0:
        break
    spot = find_free_spot(*worst_pos, max_radius=3, min_dist_x=0.55, min_dist_y=0.85)
    if spot is None:
        break  # genuinely nowhere within reach even for a pole - rare, would need a manual look
    fx, fy = spot
    pole_fill_count += 1
    pole_id = f"pole_gap_{pole_fill_count}"
    bp.entities.append(ElectricPole(name="medium-electric-pole", id=pole_id, position=(fx, fy), quality="legendary"))
    mark_occupied(fx, fy)
    nearest_id, nearest_x, nearest_y, _ = nearest_power(fx, fy)
    link_id, link_pos = power_bridge(nearest_id, (nearest_x, nearest_y), (fx, fy))
    bp.add_power_connection(pole_id, link_id)
    worst_slack, worst_pos = _register_power_source((pole_id, fx, fy, 3.5))

print(f"Gap-fill: {gap_fill_count} extra substations, {pole_fill_count} poles (+{_power_relay_counter} power relays), worst remaining slack: {worst_slack:.2f} tiles (<=0 means fully covered)")

# electric-energy-interface must be named explicitly (draftsman's default
# resolves to a different, non-power debug variant) - it only holds/
# produces energy, no supply_area of its own, so it relies on sitting near
# a substation and Factorio's normal auto-connect-on-construction (same
# as demo_export.py - draftsman rejects EEI as "not power connectable"
# for an explicit add_power_connection call). Anchored on sub_(0,0)'s
# actual (possibly nudged) position if it exists, else whichever
# substation did get placed - (0,0) itself could have been skipped.
anchor_x, anchor_y = sub_positions.get((0, 0), next(iter(sub_positions.values())))
eei_spot = find_free_spot(anchor_x - 3, anchor_y)
eei_x, eei_y = eei_spot if eei_spot is not None else (anchor_x - 3, anchor_y)
eei = ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=(eei_x, eei_y), buffer_size=10**9)
bp.entities.append(eei)

print(f"Power: {len(sub_lattice)} substations ({n_rows}x{n_cols} lattice, {sub_links} links, {nudged} nudged, {skipped} collision-skipped, {empty_skipped} empty-skipped) + 1 EEI, covering ({min_x:.0f},{min_y:.0f}) to ({max_x:.0f},{max_y:.0f})")

blueprint_string = bp.to_string()
with open(_OUTPUT_FILE, "w") as f:
    f.write(blueprint_string)
print(f"Total entities: {len(bp.entities)}")
print(f"Saved {_OUTPUT_FILE}")

# ---- numeric sanity check: same math the combinators should compute for
# the TEST_INPUT baked in above - lets the expected winner be predicted
# BEFORE touching the game (Решение 5 methodology: verify against a
# script-read signal dump, not by eyeballing) ----
import numpy as np


def window_codes(codes):
    out = []
    for w in range(len(codes) - 2):
        vals = [codes[w + k] if codes[w + k] is not None else 0 for k in range(3)]
        out.append(vals[0] * 729 + vals[1] * 27 + vals[2])
    return out


wcodes = window_codes(TEST_INPUT)
vocab_codes = [window_code(s) for s in VOCAB]
hidden_pre = np.array(b1, dtype=np.float64)
matches = []
for w, code in enumerate(wcodes):
    for s, vc in enumerate(vocab_codes):
        if code == vc:
            matches.append((w, VOCAB[s]))
            hidden_pre = hidden_pre + np.array(W1[s], dtype=np.float64)
hidden = np.maximum(0, hidden_pre)
logits = hidden @ np.array(W2, dtype=np.float64) + np.array(b2, dtype=np.float64)
ranked = sorted(range(len(CLASSES)), key=lambda i: -logits[i])
winner_idx = ranked[0]

print(f"\n--- numeric verification (TEST_INPUT) ---")
print(f"Input: position 0=space, positions 1-{len(VOCAB[0])}='{VOCAB[0]}', rest blank")
print(f"Syllable detector matches: {matches}")
print(f"Expected winner: class {winner_idx} = '{CLASSES[winner_idx]}' (logit={logits[winner_idx]:.1f})")
print(f"Runner-up: class {ranked[1]} = '{CLASSES[ranked[1]]}' (logit={logits[ranked[1]]:.1f})")
print(f"Expect in-game: exactly one decider outputs signal '{WINNER_SIGNALS[winner_idx]}'=1 (argmax's winner-take-all for class {winner_idx}), no other WINNER_SIGNALS entry should appear anywhere")
