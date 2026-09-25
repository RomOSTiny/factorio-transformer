"""Components of the FINAL model (delivered d=256 model, Reshenie 49-51), semantics = final_ref.IntModel.

Signals: every data vector (dims / keys / ffn) uses NON-virtual signals from sigkeys.pool (items,
fluids, entities, recipes, ...), so it can never collide with the virtual control / scalar signals
(signal-P, signal-W, signal-E, ...) or the vocab letters. Verified live: 2169 signals per network.

place_vec_matmul  y = trunc((x . W_o + b_o*100) / 1000), optional relu. Vector weight packing
                  (Reshenie 50): per output row ONE constant (the row of W on its private green
                  network) + ONE arithmetic each(red x) * each(green w) -> out_o. Rows in columns of
                  `rows_per_col`, snaking (even columns down, odd up); the x network (red, inputs)
                  chains through every row, the row outputs of one group chain (red, outputs) into a
                  bias constant + ONE rescale each/1000 (+ relu each>0). Groups = separate output
                  networks (QKV: q / k / v).
place_final_ln    LayerNorm, final_ref.IntModel.layernorm exactly.
"""
import math

from draftsman.entity import DeciderCombinator

import sigkeys as SK
from circuit_builder import EACH, G, R, Sub, cond, out_const

ROWS_PER_GROUP, STRIP_STEP = 4, 10
COL_W = 3
SUB_EVERY = 4           # a substation on every strip every SUB_EVERY columns (12 tiles)
DATA_TYPES = ("item", "fluid", "entity", "recipe", "space-location", "asteroid-chunk", "quality")


DELIVERY_CODE = r"E:\dev\modelgame\delivery\code"
CHARS = list("abcdefghijklmnopqrstuvwxyz .,!?'\"-\n:")          # the delivered vocab, index = token id
CHAR_SIG = {".": "signal-letter-dot", ",": "signal-comma", "!": "signal-exclamation-mark", "?": "signal-question-mark",
            "'": "signal-apostrophe", '"': "signal-quotation-mark", "-": "signal-minus", " ": "signal-dot",
            "\n": "signal-rightwards-leftwards-arrow", ":": "signal-colon"}
VOCAB_SIGS = [CHAR_SIG.get(ch, f"signal-{ch.upper()}") for ch in CHARS]


def data_signals(n_dim, n_key, n_ffn):
    """dims, keys, ffs - disjoint, all non-virtual."""
    p = SK.pool(n_dim + n_key + n_ffn, types=DATA_TYPES)
    return p[:n_dim], p[n_dim:n_dim + n_key], p[n_dim + n_key:]


def row_y(r):
    g, k = divmod(r, ROWS_PER_GROUP)
    return g * STRIP_STEP + 2 + k * 2


def mm_size(n_out, rows_per_col):
    ncols = math.ceil(n_out / rows_per_col)
    return ncols * COL_W, math.ceil(min(n_out, rows_per_col) / ROWS_PER_GROUP) * STRIP_STEP + 1


def place_vec_matmul(B, pfx, ox, oy, Wq, bias_acc, in_sigs, out_sigs, relu=False, groups=None, rows_per_col=256):
    """Wq: [n_out][n_in] ints (weights * 1000), bias_acc: [n_out] ints (= round(b*1000) * 100) or None.

    Footprint: x 0..ncols*3, y 0..height (mm_size); group tails (bias, rescale, relu) above (y -4..-1),
    one tail block of 3 tiles per group at the x of the group's first column.
    Returns dict(xin=[(id, 'input')...], outs=[[(id, 'output')], ...] per group).
    """
    b = Sub(B, pfx, ox, oy)
    n_out, n_in = len(Wq), len(Wq[0])
    assert len(in_sigs) == n_in and len(out_sigs) == n_out
    groups = groups or [(n_out, R)]
    assert sum(n for n, _ in groups) == n_out
    rpc = rows_per_col
    ncols = math.ceil(n_out / rpc)

    def cell(o):
        c, r = divmod(o, rpc)
        if c % 2:
            r = min(rpc, n_out - c * rpc) - 1 - r if c == ncols - 1 else rpc - 1 - r
        return c * COL_W, row_y(r)

    group_of = []
    for gi, (n, _) in enumerate(groups):
        group_of += [gi] * n
    for o in range(n_out):
        x, y = cell(o)
        b.const(f"w_{o}", x, y, {in_sigs[i]: int(w) for i, w in enumerate(Wq[o]) if int(w)})
        b.arith(f"d_{o}", x + 1, y, EACH, "*", EACH, out_sigs[o], R, G)
        b.wire(G, f"w_{o}", f"d_{o}", s2="input")
        if o:
            b.wire(R, f"d_{o - 1}", f"d_{o}", s1="input", s2="input")                      # X (red)
            if group_of[o] == group_of[o - 1]:
                b.wire(R, f"d_{o - 1}", f"d_{o}", s1="output", s2="output")                # group sum net
    outs, o0, used_tx = [], 0, []
    for gi, (n, colour) in enumerate(groups):
        tx = (o0 // rpc) * COL_W
        if used_tx and tx <= used_tx[-1]:
            tx = used_tx[-1] + COL_W
        used_tx.append(tx)
        ty = -4
        rs = f"rs_{gi}"
        b.arith(rs, tx, ty, EACH, "/", 1000, EACH)
        if bias_acc is not None:
            b.const(f"bias_{gi}", tx + 1, ty, {out_sigs[o]: int(bias_acc[o]) for o in range(o0, o0 + n) if int(bias_acc[o])})
            b.wire(R, f"bias_{gi}", rs, s2="input")
        near = min(range(o0, o0 + n), key=lambda o: math.dist(b.pos[f"d_{o}"], b.pos[rs]))
        B.link(R, b.id(f"d_{near}"), "output", b.id(rs), "input", b.id(f"t{gi}"))
        end = rs
        if relu:
            b.comb(DeciderCombinator, f"relu_{gi}", tx + 2, ty, conditions=[cond(EACH, ">", 0)],
                   outputs=[DeciderCombinator.Output(signal=EACH, copy_count_from_input=True)])
            b.wire(R, rs, f"relu_{gi}", s1="output", s2="input")
            end = f"relu_{gi}"
        outs.append([(b.id(end), "output")])
        o0 += n
    # power: strips between row groups, a substation every SUB_EVERY columns
    n_strips = math.ceil(min(n_out, rpc) / ROWS_PER_GROUP) + 1
    for gy in range(n_strips):
        for c in range(0, ncols + SUB_EVERY - 1, SUB_EVERY):
            b.substation(f"sub_{gy}_{c}", min(c, ncols - 1) * COL_W if c < ncols else (ncols - 1) * COL_W + 1, gy * STRIP_STEP)
    return dict(xin=[(b.id(f"d_{o}"), "input") for o in range(n_out)], outs=outs)


# ---------------------------------------------------------------- chat controller

L_SIG = "signal-info"           # prompt length: cells j < L are pins (host text), never overwritten
HALT_SIG = "signal-no-entry"    # the clock pauses while the current token is a GENERATED newline (P >= L)
NL_SIG = "signal-rightwards-leftwards-arrow"


def place_chat_controller(B, pfx, ox, oy, ctx, Tp, Tc, prompt_sigs, vocab_sigs, chars, pos_sig, w_sig, r_sig):
    """model_blocks.place_controller with host-writable pins, so a chat can continue without a rebuild.

    Every token cell j has a pin constant (the host's text; the prompt at build time) on the cell network
    next to the sample-and-hold pair. The gate writes NEXT into cell j only when WT = j + 1 AND L <= j,
    L = prompt length from cmd_src (CMD green -> lpass -> TCTL red, lpass2 -> CTRL red). The clock pauses by
    itself at the start of position P when the token of P is a newline and P >= L (the reply is complete):
    halt = TOKEN newline AND P >= L -> HALT on CMD; clk_gate needs HALT = 0. The host (RCON):
    cmd_src = {RUN, L}; after the pause it writes the next user turn into the pins after the reply's newline
    and raises L past it - the pause lifts, the KV cache keeps the history, nothing is recomputed.
    RST clears the clock, the hold cells and the KV cache (a context overflow restarts from position 0).
    """
    from draftsman.entity import DisplayPanel
    from draftsman.signatures import Condition
    from model_blocks import CLK, PH, RST, RUN, SUB_STEP, WT
    from circuit_builder import EVERYTHING, out_copy
    b = Sub(B, pfx, ox, oy)
    D = DeciderCombinator
    b.const("cmd_src", 0, 0, {L_SIG: len(prompt_sigs)})
    b.comb(D, "clk_gate", 1, 0, conditions=[cond(CLK, "<", ctx * Tp - 1, net=R), cond(RUN, ">", 0, net=G, ct="and"),
                                            cond(HALT_SIG, "=", 0, net=G, ct="and")],
           outputs=[out_const(CLK, 1)])
    b.comb(D, "clk_acc", 2, 0, conditions=[cond(RST, "=", 0, net=G)], outputs=[out_copy(CLK, R)])
    b.arith("lpass2", 7, 0, L_SIG, "+", 0, L_SIG)
    b.comb(D, "halt", 7, 3, conditions=[cond(NL_SIG, ">", 0, net=G),
                                         D.Condition(first_signal=pos_sig, comparator="≥", second_signal=L_SIG,
                                                     first_signal_networks={R}, second_signal_networks={R}, compare_type="and")],
           outputs=[out_const(HALT_SIG, 1)])
    b.arith("pos", 3, 0, CLK, "/", Tp, pos_sig)
    b.arith("w", 4, 0, CLK, "/", Tp, w_sig)
    b.const("wone", 5, 0, {w_sig: 1})
    b.arith("rpass", 6, 0, RST, "+", 0, r_sig)
    b.arith("ph", 1, 3, CLK, "%", Tp, PH)
    b.arith("wt", 2, 3, CLK, "/", Tp, WT)
    b.const("wttwo", 3, 3, {WT: 2})
    b.comb(D, "wt_gate", 4, 3, conditions=[cond(PH, "≥", Tc, net=R)], outputs=[out_copy(WT, R)])
    b.arith("rst2", 5, 3, RST, "+", 0, RST)
    b.arith("lpass", 6, 3, L_SIG, "+", 0, L_SIG)
    w = b.wire
    w(R, "clk_gate", "clk_acc", s1="output", s2="output")
    w(R, "clk_acc", "clk_acc", s1="output", s2="input")
    w(R, "clk_acc", "clk_gate", s1="input", s2="input")
    for e in ("pos", "w"):
        w(R, "clk_acc", e, s1="input", s2="input")
    w(R, "clk_gate", "ph", s1="input", s2="input")
    w(R, "ph", "wt", s1="input", s2="input")
    w(G, "cmd_src", "clk_gate", s2="input")
    w(G, "clk_gate", "clk_acc", s1="input", s2="input")
    w(G, "clk_acc", "rpass", s1="input", s2="input")
    w(G, "clk_gate", "rst2", s1="input", s2="input")
    w(G, "rst2", "lpass", s1="input", s2="input")
    w(R, "pos", "w", s1="output", s2="output")
    w(R, "w", "wone", s1="output")
    w(R, "w", "rpass", s1="output", s2="output")
    w(R, "ph", "wt", s1="output", s2="output")
    w(R, "wt", "wttwo", s1="output")
    w(R, "wt", "wt_gate", s1="output", s2="input")
    w(R, "wt_gate", "rst2", s1="output", s2="output")
    w(R, "rst2", "lpass", s1="output", s2="output")          # TCTL (red): WT gated, RST, L
    w(G, "rpass", "lpass2", s1="input", s2="input")          # CMD -> lpass2
    w(R, "rpass", "lpass2", s1="output", s2="output")        # CTRL (red): P, W, R, L
    w(R, "lpass2", "halt", s1="output", s2="input")          # halt reads P, L (red)
    w(G, "halt", "clk_gate", s1="output", s2="input")        # HALT -> CMD (green)
    for j in range(ctx):
        x = 10 + j
        b.entity(DisplayPanel, f"panel_{j}", x, 0, 1, 1, always_show_in_alt_mode=True,
                 messages=[DisplayPanel.Message(icon=vocab_sigs[k], text=chars[k],
                                                condition=Condition(first_signal=vocab_sigs[k], comparator=">", constant=0))
                           for k in range(len(vocab_sigs))])
        b.const(f"pin_{j}", x, 1, {prompt_sigs[j]: 1} if j < len(prompt_sigs) else {})
        b.comb(D, f"gate_{j}", x, 2, conditions=[cond(WT, "=", j + 1, net=R), cond(L_SIG, "≤", j, net=R, ct="and")],
               outputs=[out_copy(EVERYTHING, G)])
        b.comb(D, f"hold_{j}", x, 4, conditions=[cond(WT, "!=", j + 1, net=R), cond(RST, "=", 0, net=R, ct="and")],
               outputs=[out_copy(EVERYTHING, G)])
        b.comb(D, f"mux_{j}", x, 6, conditions=[cond(pos_sig, "=", j, net=R)], outputs=[out_copy(EVERYTHING, G)])
        w(G, f"gate_{j}", f"hold_{j}", s1="output", s2="input")
        w(G, f"hold_{j}", f"hold_{j}", s1="output", s2="input")
        w(R, f"gate_{j}", f"hold_{j}", s1="input", s2="input")
        w(G, f"hold_{j}", f"mux_{j}", s1="input", s2="input")
        w(G, f"panel_{j}", f"pin_{j}")
        w(G, f"pin_{j}", f"hold_{j}", s2="input")
        if j:
            w(R, f"gate_{j - 1}", f"gate_{j}", s1="input", s2="input")
            w(G, f"gate_{j - 1}", f"gate_{j}", s1="input", s2="input")
            w(R, f"mux_{j - 1}", f"mux_{j}", s1="input", s2="input")
            w(G, f"mux_{j - 1}", f"mux_{j}", s1="output", s2="output")
    w(G, "halt", "mux_0", s1="input", s2="output")           # TOKEN (green) -> halt
    for x in range(0, 10 + ctx + 2, SUB_STEP):
        b.substation(f"sub_{x}", x, 8)
    return dict(cmd=b.id("cmd_src"), ctrl=[(b.id("pos"), "output")], ctrl_mux=[(b.id("mux_0"), "input")],
                token=[(b.id(f"mux_{j}"), "output") for j in range(ctx)],
                next=[(b.id(f"gate_{j}"), "input") for j in range(ctx)], tctl=[(b.id("wt_gate"), "output")],
                tctl_gate=[(b.id("gate_0"), "input")])


# ---------------------------------------------------------------- LayerNorm

K_OFF = 1_000_000               # x + K is never 0 (|x| <= 3e3)
C1 = 20_000                     # E + 32 + 64*C1 > 0 (|E| <= 256*3e3 = 7.7e5 < 1.28e6)
E_, F_, J_, G4_, V_, S_, T_ = ("signal-E", "signal-F", "signal-J", "signal-G", "signal-V", "signal-S", "signal-T")


def place_final_ln(B, pfx, ox, oy, gq, bq, sigs, eps_q, n_iter=4, k_max=15):
    """out = trunc((D*250/s * g + b*1000) / 1000), D = 256x - E, s = isqrt(sum(4x - round(E/64))^2 + eps_q).

    Footprint x 0..9, y 0..9 (substation at (8, 4)). Ports: xin (red input of sum/xk), outs[0] (red output).
    """
    dim = len(sigs)
    assert dim == len(gq) == len(bq)
    b = Sub(B, pfx, ox, oy)
    A = b.arith
    # y=0: data path
    A("xk", 0, 0, EACH, "+", EACH, EACH, R, G)                 # x + K (all dims present)
    A("x256", 1, 0, EACH, "*", dim, EACH)
    A("dD", 2, 0, EACH, "-", F_, EACH, R, G)                   # D = 256(x+K) - (E + 256K)
    A("x250", 3, 0, EACH, "*", 250, EACH)
    A("norm", 4, 0, EACH, "/", S_, EACH, R, G)
    A("gam", 5, 0, EACH, "*", EACH, EACH, R, G)
    A("out", 6, 0, EACH, "/", 1000, EACH)
    b.const("kvec", 7, 0, {s: K_OFF for s in sigs})
    b.const("gamma", 7, 1, {s: int(g) for s, g in zip(sigs, gq) if int(g)})
    b.const("beta", 8, 0, {s: int(v) * 1000 for s, v in zip(sigs, bq) if int(v)})
    # y=2: scalars
    A("sum", 0, 2, EACH, "+", 0, E_)
    A("fcomb", 1, 2, E_, "+", dim * K_OFF, F_)
    A("er1", 2, 2, E_, "+", 32 + 64 * C1, J_)
    A("er2", 3, 2, J_, "/", 64, J_)
    A("er3", 4, 2, J_, "+", 4 * K_OFF - C1, G4_)
    A("xk4", 5, 2, EACH, "*", 4, EACH)
    A("dq", 6, 2, EACH, "-", G4_, EACH, R, G)
    A("sq", 7, 2, EACH, "*", EACH, V_)
    b.const("veps", 8, 2, {V_: eps_q})
    b.const("sone", 8, 3, {S_: 1})
    # y=4: Newton a_i = V/S -> T, b_i = each/2 -> S ; y=6,8: s0 bank V >= 4^k -> S = 2^(k-1)
    for i in range(1, n_iter + 1):
        A(f"a{i}", 2 * (i - 1), 4, V_, "/", S_, T_)
        A(f"b{i}", 2 * (i - 1) + 1, 4, EACH, "/", 2, S_)
    for k in range(1, k_max + 1):
        x, y = (k - 1, 6) if k <= 8 else (k - 9, 8)
        b.comb(DeciderCombinator, f"s0_{k}", x, y, conditions=[cond(V_, "≥", 4 ** k)], outputs=[out_const(S_, 2 ** (k - 1))])
    w = b.wire
    # XIN (red): xk, sum
    w(R, "xk", "sum", s1="input", s2="input")
    w(G, "kvec", "xk", s2="input")
    # E net: sum -> fcomb, er1
    w(R, "sum", "fcomb", s1="output", s2="input")
    w(R, "fcomb", "er1", s1="input", s2="input")
    w(R, "er1", "er2", s1="output", s2="input")
    w(R, "er2", "er3", s1="output", s2="input")
    # XK net: xk -> x256, xk4
    w(R, "xk", "x256", s1="output", s2="input")
    w(R, "x256", "xk4", s1="input", s2="input")
    w(R, "x256", "dD", s1="output", s2="input")
    w(G, "fcomb", "dD", s1="output", s2="input")               # F (green)
    w(R, "xk4", "dq", s1="output", s2="input")
    w(G, "er3", "dq", s1="output", s2="input")                 # G4 (green)
    w(R, "dq", "sq", s1="output", s2="input")
    # VNET (red): sq out, veps, a_i inputs, s0 inputs
    w(R, "sq", "veps", s1="output")
    w(R, "sq", f"a{n_iter}", s1="output", s2="input")
    for i in range(n_iter, 1, -1):
        w(R, f"a{i}", f"a{i - 1}", s1="input", s2="input")
    w(R, "a1", "s0_1", s1="input", s2="input")
    for k in range(2, k_max + 1):
        prev = f"s0_{k - 1}" if k != 9 else "s0_1"
        w(R, prev, f"s0_{k}", s1="input", s2="input")
        w(G, prev, f"s0_{k}", s1="output", s2="output")        # S0 (green)
    w(G, "s0_8", "sone", s1="output")
    w(G, "s0_1", "a1", s1="output", s2="input")
    for i in range(1, n_iter + 1):
        w(G, f"a{i}", f"b{i}", s1="input", s2="input")
        w(R, f"a{i}", f"b{i}", s1="output", s2="input")
        if i < n_iter:
            w(G, f"b{i}", f"a{i + 1}", s1="output", s2="input")
    w(G, f"b{n_iter}", "norm", s1="output", s2="input")        # S final (green)
    # back chain
    w(R, "dD", "x250", s1="output", s2="input")
    w(R, "x250", "norm", s1="output", s2="input")
    w(R, "norm", "gam", s1="output", s2="input")
    w(G, "gamma", "gam", s2="input")
    w(R, "gam", "out", s1="output", s2="input")
    w(R, "gam", "beta", s1="output")
    b.substation("sub", 8, 4)
    return dict(xin=[(b.id("xk"), "input"), (b.id("sum"), "input")], outs=[[(b.id("out"), "output")]])
