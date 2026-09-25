"""
Reusable generator for the parametrized spatial matmul+bias block, factored
out of stage2_matmul_param.py (QKV instance, closed live 15.09.2026 - exact
match on the first clean build). Same design, generalized to arbitrary
N_IN/N_OUT/weights/bias/input values so it can produce every matmul
instance the Sequencer DAG needs (proj, fc1, fc2, logits) without
re-deriving the geometry each time.

Call build_matmul(...) to get a (blueprint_string, id_map, expected) tuple;
the caller writes files and prints its own summary.
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

SCALE = 100
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
RED, GREEN = "red", "green"
RELAY_HOP = 7


def q(x):
    return int(round(x * SCALE))


def build_matmul(label, N_IN, N_OUT, W, b, X_ALL, T, K=1000, OFFSET=0, relu=False):
    """
    N_IN, N_OUT: matmul dimensions. W: [N_IN][N_OUT] real weights.
    b: [N_OUT] real bias. X_ALL: [T][N_IN] real input values per position
    (the live input buffer, build-time-constant for this isolated test).
    relu: apply max(0, .) after bias+rescale (for fc1).
    Returns (bp_string, idmap_list, expected[T][N_OUT]).
    """
    assert N_IN <= len(LETTERS)
    X_SIGS = [f"signal-{LETTERS[i]}" for i in range(N_IN)]
    CLK_SIG, SH_SIG, POS_SIG, TMOD_SIG = "signal-red", "signal-green", "signal-8", "signal-9"
    OBUF_SIG = "signal-grey"
    PULSE = K * 7 // 10

    bp = Blueprint()
    bp.label = label
    _bridge_ctr = [0]

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
                nx, ny_ = x + px * step * s, y + py * step * s
                if free(nx, ny_):
                    return (nx, ny_)
            step += 0.5
        return pos

    def bridge(from_id, from_pos, to_pos, color, hop=RELAY_HOP):
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
            _bridge_ctr[0] += 1
            bid = f"gbridge_{_bridge_ctr[0]}"
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

    def adder_tree(term_ids, dest_prefix, origin_x, origin_y, out_sig="signal-P"):
        """N-term pairwise adder tree (generalizes the 4-term version:
        pair up consecutive terms, then recurse on the partial sums).
        Each level gets its own X column (spaced well past RELAY_HOP so
        cross-level bridges never bundle close together) and each level's
        nodes are spaced 6 tiles apart vertically (matching the terms'
        own spacing) - found live (fc2, N_IN=8, 3 tree levels) that a
        tight 3-tile vertical spacing let adjacent pairs' convergent
        bridges nudge into each other's territory."""
        level = list(term_ids)
        level_idx = 0
        while len(level) > 1:
            nxt = []
            for i in range(0, len(level), 2):
                if i + 1 >= len(level):
                    nxt.append(level[i])
                    continue
                a_id, a_pos = level[i]
                b_id, b_pos = level[i + 1]
                sid = f"{dest_prefix}_L{level_idx}_{i}"
                spos = (origin_x, origin_y + i * 6)
                s = ArithmeticCombinator(id=sid, position=spos, first_operand=out_sig, operation="+", second_operand=0, output_signal=out_sig)
                bp.entities.append(s)
                bridge_to(a_id, a_pos, sid, spos, RED)
                bridge_to(b_id, b_pos, sid, spos, RED)
                nxt.append((sid, spos))
            level = nxt
            origin_x += 12
            level_idx += 1
        return level[0]

    IN_X, IN_Y = 2000, 0
    MM_X, MM_Y = 2000, 200
    ROW_DY = max(24, (max(N_IN, 2) // 2 - 1) * 6 + 30)
    BUS_X = MM_X - 15
    CTL_X = MM_X + max(24, N_IN * 2 + 18)
    CTL2_X, CTL2_Y = MM_X + max(40, N_IN * 2 + 34), MM_Y - 20

    e_tctr = ArithmeticCombinator(id="e_tctr", position=(IN_X + 0.5, IN_Y - 12.0), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
    bp.entities.append(e_tctr)
    bp.add_circuit_connection(RED, "e_tctr", "e_tctr", side_1="output", side_2="input")
    e_sh = ArithmeticCombinator(id="e_sh", position=(IN_X + 3.5, IN_Y - 12.0), first_operand=CLK_SIG, operation="-", second_operand=OFFSET, output_signal=SH_SIG)
    bp.entities.append(e_sh)
    bp.add_circuit_connection(RED, "e_tctr", "e_sh", side_1="output", side_2="input")
    e_pos = ArithmeticCombinator(id="e_pos", position=(IN_X + 0.5, IN_Y - 9.0), first_operand=SH_SIG, operation="/", second_operand=K, output_signal=POS_SIG)
    bp.entities.append(e_pos)
    bp.add_circuit_connection(RED, "e_sh", "e_pos", side_1="output", side_2="input")

    POSDIST_X, XBUF0_X, XMUX0_X, XSEL_X = IN_X - 14, IN_X - 12, IN_X - 7.0, IN_X - 3.0
    prev_pd = None
    for i in range(N_IN):
        pd = f"x_posdist_{i}"
        bp.entities.append(ArithmeticCombinator(id=pd, position=(POSDIST_X, IN_Y + i * 6), first_operand=POS_SIG, operation="+", second_operand=0, output_signal=POS_SIG))
        if prev_pd is None:
            bridge_to("e_pos", (IN_X + 0.5, IN_Y - 9.0), pd, (POSDIST_X, IN_Y), GREEN)
        else:
            bp.add_circuit_connection(GREEN, prev_pd, pd, side_1="output", side_2="input")
        prev_pd = pd

    for i in range(N_IN):
        sig = X_SIGS[i]
        gy = IN_Y + i * 6
        for p in range(T):
            xb = ConstantCombinator(id=f"xbuf_{p}_{i}", tile_position=(int(XBUF0_X) + p * 2, int(gy)))
            xb.set_signal(index=0, name=sig, count=X_ALL[p][i])
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
        if i > 0:
            bp.add_circuit_connection(RED, f"xsel_{i - 1}", f"xsel_{i}", side_1="output", side_2="output")

    o_tctr = ArithmeticCombinator(id="o_tctr", position=(CTL2_X, CTL2_Y), first_operand=CLK_SIG, operation="+", second_operand=1, output_signal=CLK_SIG)
    bp.entities.append(o_tctr)
    bp.add_circuit_connection(RED, "o_tctr", "o_tctr", side_1="output", side_2="input")
    o_sh = ArithmeticCombinator(id="o_sh", position=(CTL2_X + 3, CTL2_Y), first_operand=CLK_SIG, operation="-", second_operand=OFFSET, output_signal=SH_SIG)
    bp.entities.append(o_sh)
    bp.add_circuit_connection(RED, "o_tctr", "o_sh", side_1="output", side_2="input")
    o_pos = ArithmeticCombinator(id="o_pos", position=(CTL2_X, CTL2_Y + 3), first_operand=SH_SIG, operation="/", second_operand=K, output_signal=POS_SIG)
    bp.entities.append(o_pos)
    bp.add_circuit_connection(RED, "o_sh", "o_pos", side_1="output", side_2="input")
    o_tmod = ArithmeticCombinator(id="o_tmod", position=(CTL2_X + 3, CTL2_Y + 3), first_operand=SH_SIG, operation="%", second_operand=K, output_signal=TMOD_SIG)
    bp.entities.append(o_tmod)
    bp.add_circuit_connection(RED, "o_sh", "o_tmod", side_1="output", side_2="input")
    o_ctlmerge = ArithmeticCombinator(id="o_ctlmerge", position=(CTL2_X, CTL2_Y + 6), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(o_ctlmerge)
    bp.add_circuit_connection(GREEN, "o_pos", "o_ctlmerge", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, "o_tmod", "o_ctlmerge", side_1="output", side_2="input")

    prev_bus_id, prev_ctl_id = None, None
    mm_out_ids = []
    for o in range(N_OUT):
        ny = MM_Y + o * ROW_DY

        group = []
        for i in range(N_IN):
            tid = f"mm_term_{o}_{i}"
            e = ArithmeticCombinator(id=tid, position=(MM_X + i * 2, ny), first_operand=X_SIGS[i], operation="*", second_operand=q(W[i][o]), output_signal="signal-P")
            bp.entities.append(e)
            if i > 0:
                bp.add_circuit_connection(RED, group[-1][0], tid, side_1="input", side_2="input")
            group.append((tid, e.position))

        brid, bpos = f"mm_bus_{o}", (BUS_X, ny)
        bp.entities.append(ArithmeticCombinator(id=brid, position=bpos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
        if prev_bus_id is not None:
            bridge_to(prev_bus_id[0], prev_bus_id[1], brid, bpos, RED)
        bridge_to(brid, bpos, group[0][0], group[0][1], RED)
        prev_bus_id = (brid, bpos)

        sum_id, sum_pos = adder_tree(group, f"mm{o}", MM_X + N_IN * 2 + 4, ny)
        bias_id, bias_pos = f"mm_bias_{o}", (sum_pos[0] + 8, sum_pos[1])
        bp.entities.append(ArithmeticCombinator(id=bias_id, position=bias_pos, first_operand="signal-P", operation="+", second_operand=q(b[o]) * SCALE, output_signal="signal-P"))
        bp.add_circuit_connection(RED, sum_id, bias_id, side_1="output", side_2="input")
        rescale_id, rescale_pos = f"mm_rescale_{o}", (bias_pos[0] + 4, bias_pos[1])
        bp.entities.append(ArithmeticCombinator(id=rescale_id, position=rescale_pos, first_operand="signal-P", operation="/", second_operand=SCALE, output_signal="signal-Y"))
        bp.add_circuit_connection(RED, bias_id, rescale_id, side_1="output", side_2="input")
        out_id, out_pos = rescale_id, rescale_pos
        if relu:
            relu_id, relu_pos = f"mm_relu_{o}", (rescale_pos[0] + 4, rescale_pos[1])
            bp.entities.append(DeciderCombinator(
                id=relu_id, position=relu_pos,
                conditions=[DeciderCombinator.Condition(first_signal="signal-Y", comparator=">", constant=0)],
                outputs=[DeciderCombinator.Output(signal="signal-Y", copy_count_from_input=True)],
            ))
            bp.add_circuit_connection(RED, rescale_id, relu_id, side_1="output", side_2="input")
            out_id, out_pos = relu_id, relu_pos
        mm_out_ids.append((out_id, out_pos))

        ctl_x_row = max(CTL_X, out_pos[0] + 4)
        crid, cpos = f"mm_ctl_{o}", (ctl_x_row, ny)
        bp.entities.append(ArithmeticCombinator(id=crid, position=cpos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
        if prev_ctl_id is None:
            bridge_to("o_ctlmerge", (CTL2_X, CTL2_Y + 6), crid, cpos, GREEN)
        else:
            bridge_to(prev_ctl_id[0], prev_ctl_id[1], crid, cpos, GREEN)
        prev_ctl_id = (crid, cpos)

        for p in range(T):
            gx = ctl_x_row + 6 + p * 4
            ag = f"ogate_{p}_{o}"
            bp.entities.append(DeciderCombinator(
                id=ag, position=(gx, ny),
                conditions=[
                    DeciderCombinator.Condition(first_signal=POS_SIG, comparator="=", constant=p, compare_type="and"),
                    DeciderCombinator.Condition(first_signal=TMOD_SIG, comparator="=", constant=PULSE, compare_type="and"),
                ],
                outputs=[DeciderCombinator.Output(signal="signal-Y", copy_count_from_input=True)],
            ))
            bridge_to(out_id, out_pos, ag, (gx, ny), RED)
            bridge_to(crid, cpos, ag, (gx, ny), GREEN)
            al = f"olat_{p}_{o}"
            bp.entities.append(ArithmeticCombinator(id=al, position=(gx, ny + 3), first_operand=OBUF_SIG, operation="+", second_operand="signal-Y", output_signal=OBUF_SIG))
            bp.add_circuit_connection(RED, al, al, side_1="output", side_2="input")
            bp.add_circuit_connection(RED, ag, al, side_1="output", side_2="input")

    bridge_to("xsel_0", (XSEL_X, IN_Y), "mm_bus_0", (BUS_X, MM_Y), RED)

    logic_count = len(bp.entities)

    _combs = []
    for i, e in enumerate(bp.entities):
        if e.name in ("arithmetic-combinator", "decider-combinator", "constant-combinator"):
            eid = getattr(e, "id", None) or f"#{i}"
            _combs.append((eid, e.position.x, e.position.y))
    _combs.sort(key=lambda t: t[1])
    overlaps = []
    for i in range(len(_combs)):
        _, xi, yi = _combs[i]
        for j in range(i + 1, len(_combs)):
            _, xj, yj = _combs[j]
            if xj - xi >= 1.0:
                break
            if abs(yj - yi) < 2.0:
                overlaps.append((_combs[i][0], _combs[j][0]))

    POWER_STEP = 16
    NUDGES = [(0, 0), (2, 2), (-2, 2), (2, -2), (-2, -2), (4, 0), (-4, 0), (0, 4), (0, -4)]
    buckets = {}
    for e in bp.entities:
        bk = (math.floor(e.position.x), math.floor(e.position.y))
        buckets.setdefault(bk, []).append(e.position)

    def is_occupied(px, py, rx=1.4, ry=2.0):
        """Anisotropic check (combinators are 1x2, not 1x1) - an isotropic
        1.4 radius let a substation land 1.5 tiles below a bridge relay
        (fc2 live build, N_IN=8) since 1.5 > 1.4 barely cleared the OLD
        check but was still within the relay's real footprint."""
        bx, by = math.floor(px), math.floor(py)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                for (ox, oy) in buckets.get((bx + dx, by + dy), []):
                    if abs(ox - px) < rx and abs(oy - py) < ry:
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
    sub_lattice = {}
    for r in range(n_rows_p):
        for c in range(n_cols_p):
            px, py = gx0 + c * POWER_STEP, gy0 + r * POWER_STEP
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
                            bp.entities.append(ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=(eeix, eeiy), buffer_size=10**9))
                            eei_placed = True
                    break

    power_links = 0
    for (r, c), (sub_id, pos_a) in sub_lattice.items():
        for nr, nc in ((r, c + 1), (r + 1, c)):
            neighbor = sub_lattice.get((nr, nc))
            if neighbor is None:
                continue
            neighbor_id, pos_b = neighbor
            if math.hypot(pos_b[0] - pos_a[0], pos_b[1] - pos_a[1]) > 18:
                continue
            bp.add_power_connection(sub_id, neighbor_id)
            power_links += 1

    bp_string = bp.to_string()
    idmap = []
    for e in bp.entities:
        eid = getattr(e, "id", None)
        if not eid:
            continue
        idmap.append({"id": eid, "x": round(e.position.x, 3), "y": round(e.position.y, 3), "name": e.name})

    expected = []
    for p in range(T):
        row = []
        for o in range(N_OUT):
            raw = sum(q(W[i][o]) * X_ALL[p][i] for i in range(N_IN)) + q(b[o]) * SCALE
            aa, bb = abs(raw), abs(SCALE)
            v = -(aa // bb) if (raw < 0) else (aa // bb)
            if relu:
                v = max(0, v)
            row.append(v)
        expected.append(row)

    meta = dict(logic_count=logic_count, total_count=len(bp.entities), overlaps=len(overlaps),
                power_links=power_links, N_IN=N_IN, N_OUT=N_OUT, T=T, K=K, PULSE=PULSE, OFFSET=OFFSET)
    return bp_string, idmap, expected, meta
