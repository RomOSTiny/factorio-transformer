"""Placeable components for the whole-model generator (all in circuit_builder.Builder).

place_dense_matmul  y = x @ W (+ b), optional relu; output rows can be split into groups that land on
                    separate networks (QKV: q red, k green, v green) — semantics of stage2_real_ref.matmul
place_embed         x = tok_emb[T] + pos_emb[P]: one decider per token / position with DIM constant
                    outputs, all summed on the output network
place_argmax        next token id = argmax(logits) (ties -> lowest id, like numpy), plus the winner's
                    own signal (a letter, for display)
Every component returns its ports as {name: [(entity id, side), ...]}; any member of a port's list is
on that network, so links may attach to whichever is closest.
"""
import math

from draftsman.entity import DeciderCombinator, DisplayPanel, SelectorCombinator
from draftsman.signatures import Condition

from circuit_builder import EACH, EVERYTHING, G, R, Sub, cond, out_const, out_copy

ROWS_PER_GROUP, STRIP_STEP, SUB_STEP = 4, 10, 10
P_SIG = "signal-P"              # row product signal inside a matmul (private network)


def row_y(o):
    g, r = divmod(o, ROWS_PER_GROUP)
    return g * STRIP_STEP + 2 + r * 2


def _strips(b, n_rows, width):
    for g in range(math.ceil(n_rows / ROWS_PER_GROUP) + 1):
        for x in range(0, width, SUB_STEP):
            b.substation(f"sub_{g}_{x}", x, g * STRIP_STEP)


def place_dense_matmul(B, pfx, ox, oy, Wq, bias_scaled, in_sigs, out_sigs, relu=False, groups=None):
    """Wq[i][o] quantized weights (ints), bias_scaled[o] = q(b)*SCALE or None, SCALE=100 rescale.

    groups: [(n_rows, colour)] partitioning the output rows into separate output networks.
    Footprint: x 0..n_in+4, y 0..ceil(n_out/4)*10+1.
    """
    b = Sub(B, pfx, ox, oy)
    n_in, n_out = len(Wq), len(Wq[0])
    assert len(in_sigs) == n_in and len(out_sigs) == n_out
    groups = groups or [(n_out, R)]
    assert sum(n for n, _ in groups) == n_out
    rx = n_in + 2
    last = []
    for o in range(n_out):
        y = row_y(o)
        for i in range(n_in):
            b.arith(f"m_{o}_{i}", 1 + i, y, in_sigs[i], "*", int(Wq[i][o]), P_SIG)
            if i:
                b.wire(R, f"m_{o}_{i - 1}", f"m_{o}_{i}", s1="input", s2="input")
                b.wire(G, f"m_{o}_{i - 1}", f"m_{o}_{i}", s1="output", s2="output")
        if o:
            b.wire(R, f"m_{o - 1}_0", f"m_{o}_0", s1="input", s2="input")
        b.arith(f"resc_{o}", rx, y, P_SIG, "/", 100, out_sigs[o])
        b.wire(G, f"m_{o}_{n_in - 1}", f"resc_{o}", s1="output", s2="input")
        if bias_scaled is not None and int(bias_scaled[o]):
            b.const(f"bias_{o}", rx + 1, y, {P_SIG: int(bias_scaled[o])})
            b.wire(G, f"bias_{o}", f"resc_{o}", s2="input")
        end = f"resc_{o}"
        if relu:
            b.comb(DeciderCombinator, f"relu_{o}", rx + 2, y, conditions=[cond(out_sigs[o], ">", 0)],
                   outputs=[DeciderCombinator.Output(signal=out_sigs[o], copy_count_from_input=True)])
            b.wire(R, f"resc_{o}", f"relu_{o}", s1="output", s2="input")
            end = f"relu_{o}"
        last.append(end)
    outs, o0 = [], 0
    for n, colour in groups:
        for o in range(o0 + 1, o0 + n):
            b.wire(colour, last[o - 1], last[o], s1="output", s2="output")
        outs.append([(b.id(last[o]), "output") for o in range(o0, o0 + n)])
        o0 += n
    _strips(b, n_out, n_in + 5)
    return dict(xin=[(b.id(f"m_{o}_0"), "input") for o in range(n_out)], outs=outs)


def place_embed(B, pfx, ox, oy, tokq, posq, dims, pos_sig, tok_sigs, cols=12):
    """Deciders "token letter t present (green) -> dims = tok_emb[t]" and "P == i (red) -> dims = pos_emb[i]".

    The token arrives one-hot (its letter signal = 1) on the green TOKEN network, the position on the
    red CTRL network; the two never share a network, so a letter signal can't be mistaken for P/W/R.
    x leaves on red at the outputs.
    """
    b = Sub(B, pfx, ox, oy)
    items = [(tok_sigs[t], ">", 0, G, v) for t, v in enumerate(tokq)] + [(pos_sig, "=", i, R, v) for i, v in enumerate(posq)]
    ids = []
    for k, (sig, cmp, val, net, vec) in enumerate(items):
        r, c = divmod(k, cols)
        x = c if r % 2 == 0 else cols - 1 - c
        eid = f"e_{k}"
        b.comb(DeciderCombinator, eid, x, row_y(r), conditions=[cond(sig, cmp, val, net=net)],
               outputs=[out_const(dims[d], int(v)) for d, v in enumerate(vec) if int(v)])
        if ids:
            b.wire(R, ids[-1], eid, s1="input", s2="input")
            b.wire(G, ids[-1], eid, s1="input", s2="input")
            b.wire(R, ids[-1], eid, s1="output", s2="output")
        ids.append(eid)
    n_rows = math.ceil(len(items) / cols)
    _strips(b, n_rows, cols + 1)
    return dict(ctrl=[(b.id(e), "input") for e in ids], token=[(b.id(e), "input") for e in ids],
                out=[(b.id(e), "output") for e in ids])


CLK, PH, WT = "signal-clock", "signal-hourglass", "signal-speed"
RUN, RST = "signal-check", "signal-deny"


def place_controller(B, pfx, ox, oy, ctx, Tp, Tc, prompt_sigs, vocab_sigs, chars, pos_sig, w_sig, r_sig):
    """Autonomous generation: clock, position/phase, KV write signal, token buffer, display.

    cmd_src (green CMD): RUN > 0 runs the clock, RST > 0 clears clock, KV cells and token cells.
    C = ticks; P = C / Tp; W = P + 1 always (KV cell P transparent while position P is computed — the
    stack reacts to a new P only ~20+ ticks later, the cell closes after 1); PH = C % Tp.
    Token cell j (j >= len(prompt)) is written with NEXT (one-hot, green) while PH >= Tc and
    WT = P + 2 == j + 1, i.e. cell P+1 gets the argmax of position P. Cells j < len(prompt) are
    prompt constants. mux_j copies cell j onto TOKEN (green) when P == j. Display panel j shows cell j.
    Layout: core x 0..6, token buffer column j at x = 10 + j (panel y0, gate/prompt y2, hold y4, mux y6).
    """
    b = Sub(B, pfx, ox, oy)
    plen = len(prompt_sigs)
    D = DeciderCombinator
    b.const("cmd_src", 0, 0, {})
    b.comb(D, "clk_gate", 1, 0, conditions=[cond(CLK, "<", ctx * Tp - 1, net=R), cond(RUN, ">", 0, net=G, ct="and")],
           outputs=[out_const(CLK, 1)])
    b.comb(D, "clk_acc", 2, 0, conditions=[cond(RST, "=", 0, net=G)], outputs=[out_copy(CLK, R)])
    b.arith("pos", 3, 0, CLK, "/", Tp, pos_sig)
    b.arith("w", 4, 0, CLK, "/", Tp, w_sig)
    b.const("wone", 5, 0, {w_sig: 1})
    b.arith("rpass", 6, 0, RST, "+", 0, r_sig)
    b.arith("ph", 1, 3, CLK, "%", Tp, PH)
    b.arith("wt", 2, 3, CLK, "/", Tp, WT)
    b.const("wttwo", 3, 3, {WT: 2})
    b.comb(D, "wt_gate", 4, 3, conditions=[cond(PH, "≥", Tc, net=R)], outputs=[out_copy(WT, R)])
    b.arith("rst2", 5, 3, RST, "+", 0, RST)
    w = b.wire
    # clock network X (red)
    w(R, "clk_gate", "clk_acc", s1="output", s2="output")
    w(R, "clk_acc", "clk_acc", s1="output", s2="input")
    w(R, "clk_acc", "clk_gate", s1="input", s2="input")
    for e in ("pos", "w"):
        w(R, "clk_acc", e, s1="input", s2="input")
    w(R, "clk_gate", "ph", s1="input", s2="input")
    w(R, "ph", "wt", s1="input", s2="input")
    # CMD (green)
    w(G, "cmd_src", "clk_gate", s2="input")
    w(G, "clk_gate", "clk_acc", s1="input", s2="input")
    w(G, "clk_acc", "rpass", s1="input", s2="input")
    w(G, "clk_gate", "rst2", s1="input", s2="input")
    # CTRL (red): P, W (+1), R
    w(R, "pos", "w", s1="output", s2="output")
    w(R, "w", "wone", s1="output")
    w(R, "w", "rpass", s1="output", s2="output")
    # Q (red): PH, WT (+2) -> wt_gate ; TCTL (red): WT gated, RST
    w(R, "ph", "wt", s1="output", s2="output")
    w(R, "wt", "wttwo", s1="output")
    w(R, "wt", "wt_gate", s1="output", s2="input")
    w(R, "wt_gate", "rst2", s1="output", s2="output")
    # token buffer + display
    gates = []
    for j in range(ctx):
        x = 10 + j
        b.entity(DisplayPanel, f"panel_{j}", x, 0, 1, 1, always_show_in_alt_mode=True,
                 messages=[DisplayPanel.Message(icon=vocab_sigs[k], text=chars[k],
                                                condition=Condition(first_signal=vocab_sigs[k], comparator=">", constant=0))
                           for k in range(len(vocab_sigs))])
        b.comb(D, f"mux_{j}", x, 6, conditions=[cond(pos_sig, "=", j, net=R)], outputs=[out_copy(EVERYTHING, G)])
        if j < plen:
            b.const(f"cell_{j}", x, 2, {prompt_sigs[j]: 1})
            cell = f"cell_{j}"
            w(G, cell, f"mux_{j}", s2="input")
            w(G, f"panel_{j}", cell)
        else:
            b.comb(D, f"gate_{j}", x, 2, conditions=[cond(WT, "=", j + 1, net=R)], outputs=[out_copy(EVERYTHING, G)])
            b.comb(D, f"hold_{j}", x, 4, conditions=[cond(WT, "!=", j + 1, net=R), cond(RST, "=", 0, net=R, ct="and")],
                   outputs=[out_copy(EVERYTHING, G)])
            w(G, f"gate_{j}", f"hold_{j}", s1="output", s2="input")
            w(G, f"hold_{j}", f"hold_{j}", s1="output", s2="input")
            w(R, f"gate_{j}", f"hold_{j}", s1="input", s2="input")
            w(G, f"hold_{j}", f"mux_{j}", s1="input", s2="input")
            w(G, f"panel_{j}", f"hold_{j}", s2="input")
            if gates:
                w(R, gates[-1], f"gate_{j}", s1="input", s2="input")
                w(G, gates[-1], f"gate_{j}", s1="input", s2="input")
            gates.append(f"gate_{j}")
        if j:
            w(R, f"mux_{j - 1}", f"mux_{j}", s1="input", s2="input")
            w(G, f"mux_{j - 1}", f"mux_{j}", s1="output", s2="output")
    for x in range(0, 10 + ctx + 2, SUB_STEP):
        b.substation(f"sub_{x}", x, 8)
    ports = dict(cmd=b.id("cmd_src"), ctrl=[(b.id("pos"), "output")], ctrl_mux=[(b.id("mux_0"), "input")],
                 token=[(b.id(f"mux_{j}"), "output") for j in range(ctx)],
                 next=[(b.id(g), "input") for g in gates], tctl=[(b.id("wt_gate"), "output")],
                 tctl_gate=[(b.id(gates[0]), "input")] if gates else [])
    return ports


def place_argmax(B, pfx, ox, oy, vocab_sigs, next_sig, big=10 ** 6):
    """logits (red, on vocab_sigs) -> next token id on next_sig and the winner's own signal.

    L' = logit * F + big + (F-1-k), F = 2^ceil(log2 V): every candidate present and distinct, ties go to
    the lowest k. Selector max -> winner (letter), `each > 0 -> each = 1`, dot with {v_k: k} -> id.
    """
    b = Sub(B, pfx, ox, oy)
    V = len(vocab_sigs)
    F = 1 << (V - 1).bit_length()
    b.arith("mul", 0, 0, EACH, "*", F, EACH)
    b.const("tie", 1, 0, {s: big + (F - 1 - k) for k, s in enumerate(vocab_sigs)})
    b.comb(SelectorCombinator, "sel", 2, 0, operation="select", select_max=True, index_constant=0)
    b.comb(DeciderCombinator, "one", 3, 0, conditions=[cond(EACH, ">", 0)], outputs=[out_const(EACH, 1)])
    b.arith("idm", 4, 0, EACH, "*", EACH, next_sig, R, G)
    b.const("idt", 5, 0, {s: k for k, s in enumerate(vocab_sigs) if k})
    b.wire(R, "mul", "tie", s1="output")
    b.wire(R, "mul", "sel", s1="output", s2="input")
    b.wire(R, "sel", "one", s1="output", s2="input")
    b.wire(R, "one", "idm", s1="output", s2="input")
    b.wire(G, "idt", "idm", s2="input")
    b.substation("sub", 0, 3)
    return dict(logits=[(b.id("mul"), "input")], next=[(b.id("idm"), "output")], letter=[(b.id("sel"), "output")],
                onehot=[(b.id("one"), "output")])
