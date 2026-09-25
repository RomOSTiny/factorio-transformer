"""
Reusable generator for the parametrized LayerNorm block, factored out of
stage2_layernorm_param.py (the h1_fp instance: x_fp -> h1_fp, closed live
05.09.2026) the same way matmul_gen_lib.py was factored out of
stage2_matmul_param.py - so the identical combinational core (sum/mean/var
-> octave detector -> oct_lower ROM -> 992-word rsqrt ROM -> per-element
normalize) can be instantiated for LN_ffn (x2_fp -> h2_fp) and LN_final
(x3_fp -> xf_fp) without re-deriving or re-debugging the geometry - only
gamma/beta/input vary between calls, and this smoke config uses gamma=1/
beta=0 (a no-op affine) for all three applications, so even those are
usually identical between calls.

Call build_layernorm(...) to get a (blueprint_string, id_map, meta) tuple;
the caller writes files, verifies live against its own reference, and
prints its own summary (same division of responsibility as
matmul_gen_lib.build_matmul). Unlike build_matmul, no offline `expected`
is computed here - the rsqrt-ROM lookup path isn't reproduced in pure
Python (same as the original file didn't); verification is live-only,
against the reference JSON's precomputed out_fp.
"""
import json
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

with open("stage2_layernorm_ref.json") as f:
    _REF = json.load(f)

SCALE = _REF["SCALE"]                              # 100
EPS_SCALED = _REF["EPS_SCALED"]                    # 1
RSQRT_FLAT = _REF["rsqrt_table"]                   # 992 words - generic table, reused by every instance
BUCKETS_PER_OCTAVE = _REF["BUCKETS_PER_OCTAVE"]    # 32
OCTAVE_MIN = _REF["OCTAVE_MIN"]                    # 0
OCTAVE_MAX = OCTAVE_MIN + _REF["N_OCTAVES"] - 1    # 30
OCT_LOWER = [2 ** o for o in range(OCTAVE_MIN, OCTAVE_MAX + 1)]  # 31 words

RED, GREEN = "red", "green"
X_SIGNALS = ["signal-A", "signal-B", "signal-C", "signal-D"]


def q(x):
    return int(round(x * SCALE))


def build_layernorm(label, X_FP_ALL, gamma_real, beta_real, T, K_LN=1000, OFFSET_LN=0):
    """
    X_FP_ALL: [T][N_IN] fixed-point input values per position (the live
    input buffer, build-time-constant for an isolated test).
    gamma_real, beta_real: [N_IN] real-valued affine params (1.0/0.0 for
    every LN application in this smoke config - a no-op affine, but
    implemented as real combinators so trained gamma/beta drop in later).
    Returns (bp_string, idmap_list, meta_dict).
    """
    N_IN = len(X_FP_ALL[0])
    assert all(len(v) == N_IN for v in X_FP_ALL)
    assert N_IN <= len(X_SIGNALS)
    assert T == len(X_FP_ALL)
    GAMMA_FP = [q(g) for g in gamma_real]
    BETA_FP = [q(b) for b in beta_real]
    PULSE = K_LN * 7 // 10
    H1_SIG = "signal-X"

    bp = Blueprint()
    bp.label = label

    ROWS_PER_COL = 4
    COL_SPACING = 4
    RELAY_HOP = 8
    _bridge_ctr = [0]

    def bridge(from_id, from_pos, to_pos, color, hop=RELAY_HOP):
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
            _bridge_ctr[0] += 1
            bid = f"gbridge_{_bridge_ctr[0]}"
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
        """Verbatim copy of the proven mechanism from stage2_octave_isolated_test.py
        (Reshenie 14/22-26/32-33) - broadcast address on cond_signal (GREEN),
        private value on out_signal (RED), rows_per_col columns of relay-hopped
        broadcast/collector spines."""
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
            # data inside a column's collector chain flows bottom-up,
            # converging at hop=0 (the topmost relay) - use hops[0] (not
            # prev_id, the bottommost) for the inter-column cascade.
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

    SV_X, SV_Y = 2000, 0          # sum/mean/sumsq/var/vpe
    OCT_X, OCT_Y = 2000, 100      # 30 comparators (reused mechanism, no sweep)
    OLROM_X, OLROM_Y = 2000, 300  # oct_lower ROM (31 words)
    CALC_X, CALC_Y = 2000, 500    # diff/half_lower/s/addr combine
    RSQRT_X, RSQRT_Y = 2000, 700  # 992-word rsqrt value ROM
    NORM_X, NORM_Y = 2400, 700    # per-element normalize (4x)

    CTL_X = SV_X - 20
    ln_tctr = ArithmeticCombinator(id="ln_tctr", position=(CTL_X + 0.5, SV_Y - 12.0), first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T")
    bp.entities.append(ln_tctr)
    bp.add_circuit_connection(RED, "ln_tctr", "ln_tctr", side_1="output", side_2="input")

    ln_sh = ArithmeticCombinator(id="ln_sh", position=(CTL_X + 3.5, SV_Y - 12.0), first_operand="signal-T", operation="-", second_operand=OFFSET_LN, output_signal="signal-8")
    bp.entities.append(ln_sh)
    bp.add_circuit_connection(RED, "ln_tctr", "ln_sh", side_1="output", side_2="input")

    ln_pos = ArithmeticCombinator(id="ln_pos", position=(CTL_X + 0.5, SV_Y - 9.0), first_operand="signal-8", operation="/", second_operand=K_LN, output_signal="signal-Z")
    bp.entities.append(ln_pos)
    bp.add_circuit_connection(RED, "ln_sh", "ln_pos", side_1="output", side_2="input")

    ln_tmod = ArithmeticCombinator(id="ln_tmod", position=(CTL_X + 3.5, SV_Y - 9.0), first_operand="signal-8", operation="%", second_operand=K_LN, output_signal="signal-9")
    bp.entities.append(ln_tmod)
    bp.add_circuit_connection(RED, "ln_sh", "ln_tmod", side_1="output", side_2="input")

    POSDIST_X, XBUF0_X, XMUX0_X = SV_X - 9, SV_X - 7, SV_X - 3.0
    prev_pd = None
    for i in range(N_IN):
        pd = f"ln_posdist_{i}"
        bp.entities.append(ArithmeticCombinator(id=pd, position=(POSDIST_X, SV_Y + i * 2), first_operand="signal-Z", operation="+", second_operand=0, output_signal="signal-Z"))
        if prev_pd is None:
            bridge_to("ln_pos", (CTL_X + 0.5, SV_Y - 9.0), pd, (POSDIST_X, SV_Y), GREEN, hop=5)
        else:
            bp.add_circuit_connection(GREEN, prev_pd, pd, side_1="output", side_2="input")
        prev_pd = pd

    for i, sig in enumerate(X_SIGNALS[:N_IN]):
        gy = SV_Y + i * 2
        for p in range(T):
            xb = ConstantCombinator(id=f"xbuf_{p}_{i}", tile_position=(int(XBUF0_X) + p * 2, int(gy)))
            xb.set_signal(index=0, name=sig, count=X_FP_ALL[p][i])
            bp.entities.append(xb)
            mux = DeciderCombinator(
                id=f"xmux_{p}_{i}", position=(XMUX0_X + p * 1.5, gy),
                conditions=[DeciderCombinator.Condition(first_signal="signal-Z", comparator="=", constant=p)],
                outputs=[DeciderCombinator.Output(signal=sig, copy_count_from_input=True)],
            )
            bp.entities.append(mux)
            bp.add_circuit_connection(RED, f"xbuf_{p}_{i}", f"xmux_{p}_{i}", side_2="input")
            bp.add_circuit_connection(GREEN, f"ln_posdist_{i}", f"xmux_{p}_{i}", side_1="output", side_2="input")
        e = ArithmeticCombinator(id=f"x_{i}", position=(SV_X + 0.5, gy), first_operand=sig, operation="+", second_operand=0, output_signal=sig)
        bp.entities.append(e)
        for p in range(T):
            bp.add_circuit_connection(RED, f"xmux_{p}_{i}", f"x_{i}", side_1="output", side_2="input")
        src = ArithmeticCombinator(id=f"x_{i}_src", tile_position=(SV_X + 2, int(gy)), first_operand=sig, operation="+", second_operand=0, output_signal=sig)
        bp.entities.append(src)
        bp.add_circuit_connection(RED, f"x_{i}", f"x_{i}_src", side_1="output", side_2="input")

    sum01 = ArithmeticCombinator(id="sum01", position=(SV_X + 4.5, SV_Y + 0.5), first_operand="signal-A", operation="+", second_operand="signal-B", output_signal="signal-E")
    bp.entities.append(sum01)
    bp.add_circuit_connection(RED, "x_0", "sum01", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, "x_1", "sum01", side_1="output", side_2="input")

    sum23 = ArithmeticCombinator(id="sum23", position=(SV_X + 4.5, SV_Y + 4.5), first_operand="signal-C", operation="+", second_operand="signal-D", output_signal="signal-E")
    bp.entities.append(sum23)
    bp.add_circuit_connection(RED, "x_2", "sum23", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, "x_3", "sum23", side_1="output", side_2="input")

    sum_e = ArithmeticCombinator(id="sum_e", position=(SV_X + 8.5, SV_Y + 2.5), first_operand="signal-E", operation="+", second_operand=0, output_signal="signal-E")
    bp.entities.append(sum_e)
    bp.add_circuit_connection(RED, "sum01", "sum_e", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, "sum23", "sum_e", side_1="output", side_2="input")

    mean_e = ArithmeticCombinator(id="mean_e", position=(SV_X + 12.5, SV_Y + 2.5), first_operand="signal-E", operation="/", second_operand=N_IN, output_signal="signal-F")
    bp.entities.append(mean_e)
    bp.add_circuit_connection(RED, "sum_e", "mean_e", side_1="output", side_2="input")

    sq_ids = []
    for i, sig in enumerate(X_SIGNALS[:N_IN]):
        sqid = f"sq_{i}"
        e = ArithmeticCombinator(id=sqid, position=(SV_X + 0.5, SV_Y + 8 + i * 2), first_operand=sig, operation="*", second_operand=sig, output_signal="signal-G")
        bp.entities.append(e)
        bp.add_circuit_connection(RED, f"x_{i}", sqid, side_1="output", side_2="input")
        sq_ids.append(sqid)

    sumsq01 = ArithmeticCombinator(id="sumsq01", position=(SV_X + 4.5, SV_Y + 8.5), first_operand="signal-G", operation="+", second_operand=0, output_signal="signal-G")
    bp.entities.append(sumsq01)
    bp.add_circuit_connection(RED, "sq_0", "sumsq01", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, "sq_1", "sumsq01", side_1="output", side_2="input")

    sumsq23 = ArithmeticCombinator(id="sumsq23", position=(SV_X + 4.5, SV_Y + 12.5), first_operand="signal-G", operation="+", second_operand=0, output_signal="signal-G")
    bp.entities.append(sumsq23)
    bp.add_circuit_connection(RED, "sq_2", "sumsq23", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, "sq_3", "sumsq23", side_1="output", side_2="input")

    sumsq_e = ArithmeticCombinator(id="sumsq_e", position=(SV_X + 8.5, SV_Y + 10.5), first_operand="signal-G", operation="+", second_operand=0, output_signal="signal-G")
    bp.entities.append(sumsq_e)
    bp.add_circuit_connection(RED, "sumsq01", "sumsq_e", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, "sumsq23", "sumsq_e", side_1="output", side_2="input")

    esq_e = ArithmeticCombinator(id="esq_e", position=(SV_X + 12.5, SV_Y + 10.5), first_operand="signal-G", operation="/", second_operand=N_IN, output_signal="signal-H")
    bp.entities.append(esq_e)
    bp.add_circuit_connection(RED, "sumsq_e", "esq_e", side_1="output", side_2="input")

    mean_sq = ArithmeticCombinator(id="mean_sq", position=(SV_X + 16.5, SV_Y + 2.5), first_operand="signal-F", operation="*", second_operand="signal-F", output_signal="signal-J")
    bp.entities.append(mean_sq)
    bp.add_circuit_connection(RED, "mean_e", "mean_sq", side_1="output", side_2="input")

    var_e = ArithmeticCombinator(id="var_e", position=(SV_X + 20.5, SV_Y + 6.5), first_operand="signal-H", operation="-", second_operand="signal-J", output_signal="signal-K")
    bp.entities.append(var_e)
    bp.add_circuit_connection(RED, "esq_e", "var_e", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, "mean_sq", "var_e", side_1="output", side_2="input")

    vpe_e = ArithmeticCombinator(id="vpe_e", position=(SV_X + 24.5, SV_Y + 6.5), first_operand="signal-K", operation="+", second_operand=EPS_SCALED, output_signal="signal-V")
    bp.entities.append(vpe_e)
    bp.add_circuit_connection(RED, "var_e", "vpe_e", side_1="output", side_2="input")

    value_bc_pos = (OCT_X - 20 + 0.5, OCT_Y - 10)
    value_bc = ArithmeticCombinator(id="value_bc", position=value_bc_pos, first_operand="signal-V", operation="+", second_operand=0, output_signal="signal-V")
    bp.entities.append(value_bc)
    bridge_to("vpe_e", (SV_X + 24.5, SV_Y + 6.5), "value_bc", value_bc_pos, RED, hop=4)

    SLOT_W = 3
    SPINE_Y = OCT_Y - 3
    bc_spine_target = (OCT_X, SPINE_Y)
    bc_spine, bc_spine_pos, _ = bridge("value_bc", value_bc_pos, bc_spine_target, RED)

    bc_taps = [(bc_spine, bc_spine_pos)]
    for k in range(1, 30):
        tap_x = OCT_X + k * SLOT_W
        bc_spine, bc_spine_pos, _ = bridge(bc_spine, bc_spine_pos, (tap_x, SPINE_Y), RED)
        bc_taps.append((bc_spine, bc_spine_pos))

    for k in range(30):
        cx = OCT_X + k * SLOT_W
        cy = OCT_Y
        cmp_e = DeciderCombinator(
            id=f"cmp_{k}", position=(cx + 0.5, cy + 1.0),
            conditions=[DeciderCombinator.Condition(first_signal="signal-V", comparator=">=", constant=2 ** (k + 1))],
            outputs=[DeciderCombinator.Output(signal="signal-I", copy_count_from_input=False, constant=1)],
        )
        bp.entities.append(cmp_e)
        bp.add_circuit_connection(RED, bc_taps[k][0], f"cmp_{k}", side_1="output", side_2="input")

    collect_ids = {}
    for k in range(29, -1, -1):
        cx = OCT_X + k * SLOT_W
        cy = OCT_Y
        rid = f"collect_{k}"
        e = ArithmeticCombinator(id=rid, position=(cx + 0.5, cy + 3.0), first_operand="signal-I", operation="*", second_operand=1, output_signal="signal-I")
        bp.entities.append(e)
        collect_ids[k] = rid
        bp.add_circuit_connection(RED, f"cmp_{k}", rid, side_1="output", side_2="input")
        if k < 29:
            bp.add_circuit_connection(GREEN, collect_ids[k + 1], rid, side_1="output", side_2="input")

    o_collect_pos = (OCT_X - 15 + 0.5, OCT_Y + 3.0)
    o_collect = ArithmeticCombinator(id="o_collect", position=o_collect_pos, first_operand="signal-I", operation="+", second_operand=0, output_signal="signal-O")
    bp.entities.append(o_collect)
    bridge_to("collect_0", (OCT_X + 0.5, OCT_Y + 3.0), "o_collect", o_collect_pos, RED, standoff=3, hop=6)

    ol_entry, ol_collect_info = build_addressed_rom("olrom", OCT_LOWER, "signal-O", "signal-L", OLROM_X, OLROM_Y)
    bridge_to("o_collect", o_collect_pos, ol_entry[0], ol_entry[1], GREEN, hop=7)
    olc_id, olc_pos = ol_collect_info

    ol_local_pos = (CALC_X - 5 + 0.5, CALC_Y + 1.0)
    ol_local = ArithmeticCombinator(id="ol_local", position=ol_local_pos, first_operand="signal-L", operation="+", second_operand=0, output_signal="signal-L")
    bp.entities.append(ol_local)
    bridge_to(olc_id, olc_pos, "ol_local", ol_local_pos, GREEN, hop=8)

    v_local_pos = (CALC_X - 12 + 0.5, CALC_Y - 2.0)
    v_local = ArithmeticCombinator(id="v_local", position=v_local_pos, first_operand="signal-V", operation="+", second_operand=0, output_signal="signal-V")
    bp.entities.append(v_local)
    v_wp0_id, v_wp0_pos, _ = bridge("value_bc", value_bc_pos, (value_bc_pos[0], v_local_pos[1]), RED, hop=5)
    bridge_to(v_wp0_id, v_wp0_pos, "v_local", v_local_pos, RED, hop=5)

    diff_pos = (CALC_X + 0.5, CALC_Y + 1.0)
    diff_e = ArithmeticCombinator(id="diff_e", position=diff_pos, first_operand="signal-V", operation="-", second_operand="signal-L", output_signal="signal-M")
    bp.entities.append(diff_e)
    bridge_to("v_local", v_local_pos, "diff_e", diff_pos, RED, hop=6)
    bp.add_circuit_connection(GREEN, "ol_local", "diff_e", side_1="output", side_2="input")

    half_pos = (CALC_X + 3.5, CALC_Y + 1.0)
    half_e = ArithmeticCombinator(id="half_e", position=half_pos, first_operand="signal-L", operation="/", second_operand=32, output_signal="signal-L")
    bp.entities.append(half_e)
    bp.add_circuit_connection(GREEN, "ol_local", "half_e", side_1="output", side_2="input")

    s_pos = (CALC_X + 0.5, CALC_Y + 4.0)
    s_e = ArithmeticCombinator(id="s_e", position=s_pos, first_operand="signal-M", operation="/", second_operand="signal-L", output_signal="signal-S")
    bp.entities.append(s_e)
    bp.add_circuit_connection(RED, "diff_e", "s_e", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, "half_e", "s_e", side_1="output", side_2="input")

    o_local_pos = (CALC_X + 7.5, CALC_Y - 8.0)
    o_local = ArithmeticCombinator(id="o_local", position=o_local_pos, first_operand="signal-O", operation="+", second_operand=0, output_signal="signal-O")
    bp.entities.append(o_local)
    o_wp0_id, o_wp0_pos, _ = bridge("o_collect", o_collect_pos, (o_collect_pos[0], o_local_pos[1]), RED, hop=4.5)
    bridge_to(o_wp0_id, o_wp0_pos, "o_local", o_local_pos, RED, hop=4.5)

    o32_pos = (CALC_X + 11.5, CALC_Y - 2.0)
    o32 = ArithmeticCombinator(id="o32", position=o32_pos, first_operand="signal-O", operation="*", second_operand=BUCKETS_PER_OCTAVE, output_signal="signal-N")
    bp.entities.append(o32)
    bp.add_circuit_connection(RED, "o_local", "o32", side_1="output", side_2="input")

    addr_pos = (CALC_X + 11.5, CALC_Y + 4.0)
    addr_e = ArithmeticCombinator(id="addr_e", position=addr_pos, first_operand="signal-N", operation="+", second_operand="signal-S", output_signal="signal-Q")
    bp.entities.append(addr_e)
    bp.add_circuit_connection(RED, "o32", "addr_e", side_1="output", side_2="input")
    bridge_to("s_e", s_pos, "addr_e", addr_pos, GREEN, hop=6)

    rsqrt_entry, rsqrt_collect_info = build_addressed_rom("rsq", RSQRT_FLAT, "signal-Q", "signal-R", RSQRT_X, RSQRT_Y, rows_per_col=32)
    bridge_to("addr_e", addr_pos, rsqrt_entry[0], rsqrt_entry[1], GREEN, hop=7)
    rsqc_id, rsqc_pos = rsqrt_collect_info

    X_FAR_X = NORM_X - 6 + 0.5
    MEAN_LOCAL_X = NORM_X + 3 + 0.5
    RSQRT_LOCAL_X = NORM_X + 11 + 0.5
    SPINE_ORIGIN_Y = NORM_Y - 3.0

    rsqrt_local_pos = (RSQRT_LOCAL_X, SPINE_ORIGIN_Y)
    rsqrt_local = ArithmeticCombinator(id="rsqrt_local", position=rsqrt_local_pos, first_operand="signal-R", operation="+", second_operand=0, output_signal="signal-R")
    bp.entities.append(rsqrt_local)
    bridge_to(rsqc_id, rsqc_pos, "rsqrt_local", rsqrt_local_pos, RED, hop=8, standoff=6)

    mean_local_pos = (MEAN_LOCAL_X, SPINE_ORIGIN_Y)
    mean_local = ArithmeticCombinator(id="mean_local", position=mean_local_pos, first_operand="signal-F", operation="+", second_operand=0, output_signal="signal-F")
    bp.entities.append(mean_local)
    mean_e_pos = (SV_X + 12.5, SV_Y + 2.5)
    OCT_CLEAR_X = OCT_X + 30 * SLOT_W + 5
    mean_wp0_id, mean_wp0_pos, _ = bridge("mean_e", mean_e_pos, (OCT_CLEAR_X, mean_e_pos[1]), GREEN, hop=8)
    mean_wp1_id, mean_wp1_pos, _ = bridge(mean_wp0_id, mean_wp0_pos, (OCT_CLEAR_X, OCT_Y + 45), GREEN, hop=8)
    bridge_to(mean_wp1_id, mean_wp1_pos, "mean_local", mean_local_pos, GREEN, hop=8, standoff=6)

    x_merge_pos = (SV_X + 6, SV_Y + 3)
    x_merge = ArithmeticCombinator(id="x_merge", position=x_merge_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(x_merge)
    for i in range(N_IN):
        bp.add_circuit_connection(RED, f"x_{i}_src", "x_merge", side_1="output", side_2="input")

    x_far_pos = (X_FAR_X, SPINE_ORIGIN_Y)
    x_far = ArithmeticCombinator(id="x_far", position=x_far_pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(x_far)
    X_CLEAR_X = OCT_CLEAR_X + 15
    x_wp0a_id, x_wp0a_pos, _ = bridge("x_merge", x_merge_pos, (x_merge_pos[0], SV_Y + 25), RED, hop=6.5)
    x_wp0_id, x_wp0_pos, _ = bridge(x_wp0a_id, x_wp0a_pos, (X_CLEAR_X, SV_Y + 25), RED, hop=6.5)
    x_wp1_id, x_wp1_pos, _ = bridge(x_wp0_id, x_wp0_pos, (X_CLEAR_X, OCT_Y + 60), RED, hop=8)
    bridge_to(x_wp1_id, x_wp1_pos, "x_far", x_far_pos, RED, hop=4, standoff=6)

    def spine_with_taps(name, src_id, src_pos, color, hop=6):
        spine_prev, spine_pos = src_id, src_pos
        taps = []
        for i in range(N_IN):
            gy = NORM_Y + i * 6
            tap_pos = (src_pos[0], gy)
            tap_id, tap_pos, _ = bridge(spine_prev, spine_pos, tap_pos, color, hop=hop)
            taps.append((tap_id, tap_pos))
            spine_prev, spine_pos = tap_id, tap_pos
        return taps

    mean_taps = spine_with_taps("mean", "mean_local", mean_local_pos, GREEN, hop=6)
    rsqrt_taps = spine_with_taps("rsqrt", "rsqrt_local", rsqrt_local_pos, GREEN, hop=6.3)
    x_taps = spine_with_taps("x", "x_far", x_far_pos, RED, hop=5.7)

    for i, sig in enumerate(X_SIGNALS[:N_IN]):
        gy = NORM_Y + i * 6
        xi_local_pos = (NORM_X + 0.5, gy)
        xi_local = ArithmeticCombinator(id=f"xi_local_{i}", position=xi_local_pos, first_operand=sig, operation="+", second_operand=0, output_signal=sig)
        bp.entities.append(xi_local)
        bridge_to(x_taps[i][0], x_taps[i][1], f"xi_local_{i}", xi_local_pos, RED, hop=6, standoff=6)

        dx_pos = (NORM_X + 7.5, gy)
        dx_e = ArithmeticCombinator(id=f"dx_{i}", position=dx_pos, first_operand=sig, operation="-", second_operand="signal-F", output_signal="signal-U")
        bp.entities.append(dx_e)
        bp.add_circuit_connection(RED, f"xi_local_{i}", f"dx_{i}", side_1="output", side_2="input")
        bridge_to(mean_taps[i][0], mean_taps[i][1], f"dx_{i}", dx_pos, GREEN, hop=6, standoff=6)

        prod1_pos = (NORM_X + 15.5, gy)
        prod1_e = ArithmeticCombinator(id=f"prod1_{i}", position=prod1_pos, first_operand="signal-U", operation="*", second_operand="signal-R", output_signal="signal-U")
        bp.entities.append(prod1_e)
        bp.add_circuit_connection(RED, f"dx_{i}", f"prod1_{i}", side_1="output", side_2="input")
        bridge_to(rsqrt_taps[i][0], rsqrt_taps[i][1], f"prod1_{i}", prod1_pos, GREEN, hop=6, standoff=6)

        normed_pos = (NORM_X + 12.5, gy)
        normed_e = ArithmeticCombinator(id=f"normed_{i}", position=normed_pos, first_operand="signal-U", operation="/", second_operand=SCALE, output_signal="signal-U")
        bp.entities.append(normed_e)
        bp.add_circuit_connection(RED, f"prod1_{i}", f"normed_{i}", side_1="output", side_2="input")

        gamma_store = ConstantCombinator(id=f"gamma_{i}", tile_position=(int(NORM_X + 16), int(gy)))
        gamma_store.set_signal(index=0, name="signal-W", count=GAMMA_FP[i])
        bp.entities.append(gamma_store)

        prod2_pos = (NORM_X + 20.5, gy)
        prod2_e = ArithmeticCombinator(id=f"prod2_{i}", position=prod2_pos, first_operand="signal-U", operation="*", second_operand="signal-W", output_signal="signal-U")
        bp.entities.append(prod2_e)
        bp.add_circuit_connection(RED, f"normed_{i}", f"prod2_{i}", side_1="output", side_2="input")
        bp.add_circuit_connection(GREEN, f"gamma_{i}", f"prod2_{i}", side_2="input")

        scaled2_pos = (NORM_X + 24.5, gy)
        scaled2_e = ArithmeticCombinator(id=f"scaled2_{i}", position=scaled2_pos, first_operand="signal-U", operation="/", second_operand=SCALE, output_signal="signal-U")
        bp.entities.append(scaled2_e)
        bp.add_circuit_connection(RED, f"prod2_{i}", f"scaled2_{i}", side_1="output", side_2="input")

        out_e = ArithmeticCombinator(id=f"out_{i}", position=(NORM_X + 28.5, gy), first_operand="signal-U", operation="+", second_operand=BETA_FP[i], output_signal="signal-Y")
        bp.entities.append(out_e)
        bp.add_circuit_connection(RED, f"scaled2_{i}", f"out_{i}", side_1="output", side_2="input")

        sink_e = ArithmeticCombinator(id=f"sink_{i}", position=(NORM_X + 32.5, gy), first_operand="signal-Y", operation="+", second_operand=0, output_signal="signal-Y")
        bp.entities.append(sink_e)
        bp.add_circuit_connection(RED, f"out_{i}", f"sink_{i}", side_1="output", side_2="input")

    H1_GATE0_X = NORM_X + 34
    CTLDIST_X = NORM_X + 40
    CTL2_X = CTLDIST_X
    ln_tctr2 = ArithmeticCombinator(id="ln_tctr2", position=(CTL2_X, NORM_Y - 12.0), first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T")
    bp.entities.append(ln_tctr2)
    bp.add_circuit_connection(RED, "ln_tctr2", "ln_tctr2", side_1="output", side_2="input")
    ln_sh2 = ArithmeticCombinator(id="ln_sh2", position=(CTL2_X + 3, NORM_Y - 12.0), first_operand="signal-T", operation="-", second_operand=OFFSET_LN, output_signal="signal-8")
    bp.entities.append(ln_sh2)
    bp.add_circuit_connection(RED, "ln_tctr2", "ln_sh2", side_1="output", side_2="input")
    ln_pos2 = ArithmeticCombinator(id="ln_pos2", position=(CTL2_X, NORM_Y - 9.0), first_operand="signal-8", operation="/", second_operand=K_LN, output_signal="signal-Z")
    bp.entities.append(ln_pos2)
    bp.add_circuit_connection(RED, "ln_sh2", "ln_pos2", side_1="output", side_2="input")
    ln_tmod2 = ArithmeticCombinator(id="ln_tmod2", position=(CTL2_X + 3, NORM_Y - 9.0), first_operand="signal-8", operation="%", second_operand=K_LN, output_signal="signal-9")
    bp.entities.append(ln_tmod2)
    bp.add_circuit_connection(RED, "ln_sh2", "ln_tmod2", side_1="output", side_2="input")
    ln_ctlmerge2 = ArithmeticCombinator(id="ln_ctlmerge2", position=(CTL2_X, NORM_Y - 6.0), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(ln_ctlmerge2)
    bp.add_circuit_connection(GREEN, "ln_pos2", "ln_ctlmerge2", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, "ln_tmod2", "ln_ctlmerge2", side_1="output", side_2="input")

    prev_cd = "ln_ctlmerge2"
    for i in range(N_IN):
        cd = f"h1_ctldist_{i}"
        bp.entities.append(ArithmeticCombinator(id=cd, position=(CTLDIST_X, NORM_Y + i * 6), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
        bp.add_circuit_connection(GREEN, prev_cd, cd, side_1="output", side_2="input")
        prev_cd = cd

    for i in range(N_IN):
        gy = NORM_Y + i * 6
        for p in range(T):
            hg = f"h1gate_{p}_{i}"
            bp.entities.append(DeciderCombinator(
                id=hg, position=(H1_GATE0_X + p * 3, gy),
                conditions=[
                    DeciderCombinator.Condition(first_signal="signal-Z", comparator="=", constant=p, compare_type="and"),
                    DeciderCombinator.Condition(first_signal="signal-9", comparator="=", constant=PULSE, compare_type="and"),
                ],
                outputs=[DeciderCombinator.Output(signal="signal-Y", copy_count_from_input=True)],
            ))
            bp.add_circuit_connection(RED, f"out_{i}", hg, side_1="output", side_2="input")
            bp.add_circuit_connection(GREEN, f"h1_ctldist_{i}", hg, side_1="output", side_2="input")
            hl = f"h1lat_{p}_{i}"
            bp.entities.append(ArithmeticCombinator(id=hl, position=(H1_GATE0_X + p * 3, gy + 2.5), first_operand=H1_SIG, operation="+", second_operand="signal-Y", output_signal=H1_SIG))
            bp.add_circuit_connection(RED, hl, hl, side_1="output", side_2="input")
            bp.add_circuit_connection(RED, hg, hl, side_1="output", side_2="input")

    # ---- power: generous lattice, same auto-layout as stage2_octave_isolated_test.py ----
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
                    rid = f"sub_link_relay_{r}_{c}_{nr}_{nc}_{h}"
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

    bp_string = bp.to_string()
    idmap = []
    for e in bp.entities:
        eid = getattr(e, "id", None)
        if not eid:
            continue
        idmap.append({"id": eid, "x": round(e.position.x, 3), "y": round(e.position.y, 3), "name": e.name})

    meta = dict(total_count=len(bp.entities), N_IN=N_IN, T=T, K=K_LN, PULSE=PULSE, OFFSET=OFFSET_LN,
                sub_lattice_count=len(sub_lattice), empty_skipped=empty_skipped, gap_fill_count=gap_fill_count,
                worst_slack=worst_slack)
    return bp_string, idmap, meta
