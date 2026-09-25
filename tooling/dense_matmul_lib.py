"""Dense spatial matmul for the full-size model: ~1 entity per weight.

Grid of multipliers m(o,i) = x_i * w_oi (weight = second_operand constant, so no
weight memory). All multipliers share ONE input network (red, x_i on distinct
signals) and every row's products go onto their own output network (green) as the
SAME signal, so the circuit network SUMS them for free (no adder tree). Per row:
bias constant on the sum network, a rescale (/SCALE) and optional relu. Row outputs
land on distinct signals of one OUT network. Bias is folded before the single
rescale, exactly like stage2_real_ref.matmul.
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.data import signals as _signals
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

SCALE = 100
RED, GREEN = "red", "green"
_RESERVED = {"signal-everything", "signal-each", "signal-anything", "signal-P", "signal-T", "signal-red", "signal-green",
             "signal-8", "signal-9", "signal-Z", "signal-grey", "signal-X", "signal-Y"}


def signal_pool(n):
    pool = [s for s in _signals.virtual if s not in _RESERVED]
    assert n <= len(pool), f"need {n} signals, have {len(pool)}"
    return pool[:n]


def q(x):
    return int(round(x * SCALE))


ROWS_PER_GROUP = 4      # rows (2 tiles tall each) between two power strips
STRIP_STEP = 10         # tiles per group period: 2 (strip) + 4*2 rows
SUB_STEP = 10           # substation spacing along a strip


def build_dense_matmul(label, W, b, in_sigs, out_sigs, relu=False, x_values=None):
    """W: [N_IN][N_OUT] real weights, b: [N_OUT]. Returns (bp_string, idmap, meta)."""
    n_in, n_out = len(W), len(W[0])
    assert len(in_sigs) == n_in and len(out_sigs) == n_out
    bp = Blueprint()
    bp.label = label
    X0 = 6  # left margin for input constants
    n_groups = math.ceil(n_out / ROWS_PER_GROUP)

    def row_y(o):
        g, r = divmod(o, ROWS_PER_GROUP)
        return g * STRIP_STEP + 2 + r * 2

    mid = {}
    for o in range(n_out):
        y = row_y(o)
        for i in range(n_in):
            mid[(o, i)] = f"m_{o}_{i}"
            bp.entities.append(ArithmeticCombinator(
                id=mid[(o, i)], tile_position=(X0 + i, y), first_operand=in_sigs[i], operation="*",
                second_operand=q(W[i][o]), output_signal="signal-P"))
    # input network (red): chain along each row, then link row starts vertically
    for o in range(n_out):
        for i in range(1, n_in):
            bp.add_circuit_connection(RED, mid[(o, i - 1)], mid[(o, i)], side_1="input", side_2="input")
        if o > 0:
            bp.add_circuit_connection(RED, mid[(o - 1, 0)], mid[(o, 0)], side_1="input", side_2="input")
    # output network per row (green): chain outputs, then bias + rescale (+relu)
    rx = X0 + n_in + 1
    res_ids, out_ids = [], []
    for o in range(n_out):
        y = row_y(o)
        for i in range(1, n_in):
            bp.add_circuit_connection(GREEN, mid[(o, i - 1)], mid[(o, i)], side_1="output", side_2="output")
        rid = f"resc_{o}"
        bp.entities.append(ArithmeticCombinator(
            id=rid, tile_position=(rx, y), first_operand="signal-P", operation="/", second_operand=SCALE, output_signal=out_sigs[o]))
        bp.add_circuit_connection(GREEN, mid[(o, n_in - 1)], rid, side_1="output", side_2="input")
        bc = ConstantCombinator(id=f"bias_{o}", tile_position=(rx + 1, y))
        bc.set_signal(index=0, name="signal-P", count=q(b[o]) * SCALE)
        bp.entities.append(bc)
        bp.add_circuit_connection(GREEN, f"bias_{o}", rid, side_2="input")
        last = rid
        if relu:
            rl = f"relu_{o}"
            bp.entities.append(DeciderCombinator(
                id=rl, tile_position=(rx + 2, y),
                conditions=[DeciderCombinator.Condition(first_signal=out_sigs[o], comparator=">", constant=0)],
                outputs=[DeciderCombinator.Output(signal=out_sigs[o], copy_count_from_input=True)]))
            bp.add_circuit_connection(RED, rid, rl, side_1="output", side_2="input")
            last = rl
        out_ids.append(last)
        res_ids.append(rid)
    for o in range(1, n_out):
        bp.add_circuit_connection(RED, out_ids[o - 1], out_ids[o], side_1="output", side_2="output")
    # test/driver inputs: constants (20 signals each) feeding the shared input network
    n_const = 0
    if x_values is not None:
        for k in range(0, n_in, 20):
            cid = f"xin_{k // 20}"
            c = ConstantCombinator(id=cid, tile_position=(3, 2 + (k // 20) * 2))
            for j in range(k, min(k + 20, n_in)):
                c.set_signal(index=j - k, name=in_sigs[j], count=x_values[j])
            bp.entities.append(c)
            bp.add_circuit_connection(RED, cid, mid[(0, 0)], side_2="input")
            n_const += 1
    # power: substation strips
    width = X0 + n_in + 6
    sub_lat = {}
    for g in range(n_groups + 1):
        y = g * STRIP_STEP
        for k, x in enumerate(range(0, width, SUB_STEP)):
            sid = f"sub_{g}_{k}"
            bp.entities.append(ElectricPole(name="substation", id=sid, tile_position=(x, y), quality="legendary"))
            sub_lat[(g, k)] = sid
    for (g, k), sid in sub_lat.items():
        for nb in ((g, k + 1), (g + 1, k)):
            if nb in sub_lat:
                bp.add_power_connection(sid, sub_lat[nb])
    bp.entities.append(ElectricEnergyInterface(name="electric-energy-interface", id="power_source", tile_position=(width + 2, 0), buffer_size=10 ** 9))
    bp_string = bp.to_string()
    idmap = []
    for e in bp.entities:
        eid = getattr(e, "id", None)
        if eid:
            idmap.append({"id": eid, "x": round(e.position.x, 3), "y": round(e.position.y, 3), "name": e.name})
    meta = dict(n_in=n_in, n_out=n_out, entities=len(bp.entities), weights=n_in * n_out, per_weight=len(bp.entities) / (n_in * n_out))
    return bp_string, idmap, meta
