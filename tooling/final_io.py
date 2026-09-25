"""In-game chat I/O for the final model (no RCON, no mods): a console of constant combinators for the query,
SEND / RESET buttons, and a lamp board with a 5x7 pixel font. Replaces place_chat_controller.

Player side:
  query slots   100 constant combinators side by side in one strip above the board, one letter signal each (a-z =
                signal-A..Z, space = signal-dot, . , ! ? ' " - their signals); the query ends at the first
                empty slot or at the END mark (signal-check, the tick) - an old tail after it is ignored
  SEND          constant combinator "send" at the start of the strip, one row above it (label ОТПРАВИТЬ) -
                turn it on (then off): the query is taken
  RESET         the constant next to it (label СБРОС) - turn it on (then off): a new conversation
Board (lamps, always on):
  query line    100 characters - shows the slots live, up to the end of the query
  progress bar  30 lamps - share of the query already read by the model (red -> yellow -> green)
  reply line    150 characters - the reply appears letter by letter; SEND clears it

Circuit (the model sees `you: <query>\\nbot: ` - the role markers it was trained on - then generates until
'\\n'; the KV cache keeps the conversation):
  SEND edge (send AND NOT delayed send AND (HALT OR NOT RUN)) -> PULSE (1 tick) latches
    S = X (next free position: P + HALT), C = number of filled slots; if X + C > 94 the conversation does
    not fit (reply room 150 of ctx 256): S = 0 and WIPE (RST pulse: clock, token cells, KV cache cleared)
  L = S + C + 11 (prompt end); RUN latch set by PULSE, cleared by RESET
  query tokens  I = P - S, J = I - C: prefix deciders (I = 0..4 -> "you: "), slot deciders
                (I = 5 + k AND C > k -> copy slot k), suffix deciders (J = 5..10 -> "\\nbot: ") -> TOKEN
  token cells   generated tokens only: cell j written with NEXT when WT = j + 1 AND L <= j (as before)
  HALT          (token of P is a generated '\\n', P >= L) OR (P - L >= 150): the clock pauses
  reply cells   150 sample-and-hold cells, cell i written with NEXT when WT - L = i + 1; cleared by PULSE
  pixels        per character: code1/code2 = onehot . font table (two 20/15-bit masks),
                pixel p = (code >> shift_p) AND 1 on 35 pixel signals -> 35 lamps
"""
import math

from draftsman.entity import DeciderCombinator, DisplayPanel, Lamp, SelectorCombinator

import sigkeys as SK
from circuit_builder import EACH, EVERYTHING, G, R, Sub, cond, out_const, out_copy
from final_blocks import CHARS, VOCAB_SIGS
from font5x7 import H as FH, W as FW, codes, shift
from model_blocks import CLK, PH, RST, RUN, WT

SEND, BRST, HALT, L_SIG = "signal-input", "signal-alert", "signal-no-entry", "signal-info"
SS, CNT, X_, Z_, OK_, OVF, PULSE, SD = ("signal-S", "signal-C", "signal-X", "signal-Z", "signal-O", "signal-U",
                                        "signal-K", "signal-D")
I_, J_, Q_ = "signal-I", "signal-J", "signal-Q"
WR, CLR, DH = "signal-Y", "signal-E", "signal-H"
END, KC, CL = "signal-check", "signal-white", "signal-grey"     # END = the player's end-of-query mark (✓)
BAR = "signal-B"
NL_SIG = VOCAB_SIGS[CHARS.index("\n")]
PIX = SK.pool(35, types=("item",))              # pixel signals (private per character cell)
STOP = SK.pool(101, types=("entity",))          # per-slot stop signals (the stop network only)
_GP = SK.pool(200, types=("recipe",))
G1, G2 = _GP[:100], _GP[100:]                    # per-slot font masks on the console -> board BUS
PREFIX, SUFFIX = "you: ", "\nbot: "
REPLY_MAX = 150
FIT = 94                                          # S + C <= FIT keeps L + REPLY_MAX <= ctx - 1

D = DeciderCombinator

# how-to panels above the console (Russian, English, Chinese), one short line per panel, top to bottom
# (alt-mode labels are cut after ~65 latin / ~20 CJK characters)
INSTRUCTIONS = [
    [("signal-1", "1. Вопрос по-английски - в комбинаторы ниже"),
     (None, "по одной букве в каждый (A-Z)"),
     (None, "пробел = сигнал «Точка» (кружок)"),
     ("signal-2", "2. После последней буквы - галочка ✓"),
     ("signal-3", "3. ОТПРАВИТЬ: включи и снова выключи"),
     ("signal-4", "4. Ответ - на табло из ламп, ~7 с на букву"),
     ("signal-5", "5. СБРОС - начать новый разговор")],
    [("signal-1", "1. Type an English question below"),
     (None, "one letter per combinator (A-Z)"),
     (None, "space = Dot signal (the circle)"),
     ("signal-2", "2. After the last letter: check mark ✓"),
     ("signal-3", "3. SEND: switch it on, then off"),
     ("signal-4", "4. Answer on the lamp board, ~7 s per letter"),
     ("signal-5", "5. RESET: start a new conversation")],
    [("signal-1", "1. 在下方运算器中输入英文问题"),
     (None, "每个运算器一个字母 (A-Z)"),
     (None, "空格 = 圆点 Dot 信号"),
     ("signal-2", "2. 最后一个字母后放对勾 ✓"),
     ("signal-3", "3. 发送 SEND:打开再关闭"),
     ("signal-4", "4. 回答显示在灯板上,每字约 7 秒"),
     ("signal-5", "5. 重置 RESET:开始新对话")],
]


def cnd2(first, cmp, second, n1=R, n2=R, ct="and"):
    return D.Condition(first_signal=SK.sid(first), comparator=cmp, second_signal=SK.sid(second),
                       first_signal_networks={n1}, second_signal_networks={n2}, compare_type=ct)


def _lamp(b, eid, x, y, sig, k, color=None, use_colors=False):
    lp = Lamp(id=b.id(eid), tile_position=(b.ox + x, b.oy + y), always_on=True)
    lp.set_circuit_condition(SK.sid(sig), "≥" if k else ">", k if k else 0)
    lp.circuit_enabled = True
    if color:
        lp.color = color
    if use_colors:
        lp.use_colors = True
    b.b._place(b.id(eid), b.ox + x, b.oy + y, 1, 1)
    b.b._add(b.id(eid), lp)


def _glyph_cell(b, t, x, y_comb, y_lamps, src, color, rows2):
    """dot1/dot2/sh1/sh2/and for one character + 35 lamps. src: (entity, side) whose RED side carries the
    character one-hot (value 1). rows2: (x, y) slots for dot1, dot2, sh1, sh2, and (relative to x).
    Returns ids of dot1, dot2, sh1, sh2 (for the shared table chains)."""
    (d1x, d1y), (d2x, d2y), (s1x, s1y), (s2x, s2y), (ax, ay) = rows2
    b.arith(t + "d1", x + d1x, d1y, EACH, "*", EACH, "signal-1", R, G)
    b.arith(t + "d2", x + d2x, d2y, EACH, "*", EACH, "signal-2", R, G)
    b.arith(t + "s1", x + s1x, s1y, "signal-1", ">>", EACH, EACH, R, G)
    b.arith(t + "s2", x + s2x, s2y, "signal-2", ">>", EACH, EACH, R, G)
    b.arith(t + "and", x + ax, ay, EACH, "AND", 1, EACH, R)
    b.wire(R, src[0], t + "d1", s1=src[1], s2="input")
    b.wire(R, t + "d1", t + "d2", s1="input", s2="input")
    b.wire(R, t + "d1", t + "d2", s1="output", s2="output")
    b.wire(R, t + "d2", t + "s1", s1="output", s2="input")
    b.wire(R, t + "s1", t + "s2", s1="input", s2="input")
    b.wire(R, t + "s1", t + "s2", s1="output", s2="output")
    b.wire(R, t + "s2", t + "and", s1="output", s2="input")
    prev, prev_side = t + "and", "output"
    order = [(r, c if r % 2 == 0 else FW - 1 - c) for r in range(FH) for c in range(FW)]
    for r, c in order:
        p = r * FW + c
        lid = f"{t}px{p}"
        _lamp(b, lid, x + c, y_lamps + r, PIX[p], 0, color=color)
        b.wire(R, prev, lid, s1=prev_side)
        prev, prev_side = lid, None
    return t + "d1", t + "d2", t + "s1", t + "s2"


def _tables(b, t, x, y1, y2, chain_first):
    """The four shared font tables of one line, wired to the first cell's dot1/dot2/sh1/sh2 (green)."""
    c1 = {VOCAB_SIGS[i]: codes(ch)[0] for i, ch in enumerate(CHARS) if codes(ch)[0]}
    c2 = {VOCAB_SIGS[i]: codes(ch)[1] for i, ch in enumerate(CHARS) if codes(ch)[1]}
    b.const(t + "code1", x, y1, c1)
    b.const(t + "code2", x + 1, y1, c2)
    b.const(t + "sh1", x, y2, {PIX[p]: shift(p) for p in range(20)})
    b.const(t + "sh2", x + 1, y2, {PIX[p]: shift(p) for p in range(20, 35)})
    d1, d2, s1, s2 = chain_first
    b.wire(G, t + "code1", d1, s2="input")
    b.wire(G, t + "code2", d2, s2="input")
    b.wire(G, t + "sh1", s1, s2="input")
    b.wire(G, t + "sh2", s2, s2="input")


def _chain_tables(b, prev, cur):
    for a, c in zip(prev, cur):
        b.wire(G, a, c, s1="input", s2="input")


def place_chat_io(B, pfx, ox, oy, ctx, Tp, Tc, pos_sig, w_sig, r_sig, n_query=100, n_reply=REPLY_MAX,
                  query_color=None, reply_color=None):
    b = Sub(B, pfx, ox, oy)
    n_links = [0]

    def w(color, a, c, s1=None, s2=None):
        """Direct wire when short, else a pole route (Builder.link)."""
        if a != c and math.dist(b.pos[a], b.pos[c]) > 8.0:
            n_links[0] += 1
            B.link(color, b.id(a), s1, b.id(c), s2, b.id(f"wl{n_links[0]}"))
        else:
            b.wire(color, a, c, s1=s1, s2=s2)
    V = len(VOCAB_SIGS)
    qcol = query_color or {"r": 0.3, "g": 0.9, "b": 1.0, "a": 1}
    rcol = reply_color or {"r": 1.0, "g": 0.85, "b": 0.3, "a": 1}
    XQ, XR = 20, 20                                   # first cell x of the query / reply line
    XS, YS = 20, -20                                  # the console strip (slot k at x = XS + k)
    YQ, YR, YT = 30, 50, 70                           # query line, reply line, token cells

    # ---------------- core: clock (as place_chat_controller) ----------------
    for k, (x, y) in enumerate(((4, -3), (13, 4), (4, 10), (13, 16), (0, 22), (10, 22))):
        b.substation(f"csub{k}", x, y)
    b.const("cmd_src", 0, 0, {})                                                   # RCON override (debug)
    b.comb(D, "clk_gate", 1, 0, conditions=[cond(CLK, "<", ctx * Tp - 1, net=R), cond(RUN, ">", 0, net=G, ct="and"),
                                            cond(HALT, "=", 0, net=G, ct="and")], outputs=[out_const(CLK, 1)])
    b.comb(D, "clk_acc", 2, 0, conditions=[cond(RST, "=", 0, net=G)], outputs=[out_copy(CLK, R)])
    b.arith("pos", 3, 0, CLK, "/", Tp, pos_sig)
    b.arith("w", 4, 0, CLK, "/", Tp, w_sig)
    b.const("wone", 5, 0, {w_sig: 1})
    b.arith("rpass", 6, 0, RST, "+", 0, r_sig)
    b.arith("lpass2", 7, 0, L_SIG, "+", 0, L_SIG)
    b.arith("ph", 1, 3, CLK, "%", Tp, PH)
    b.arith("wt", 2, 3, CLK, "/", Tp, WT)
    b.const("wttwo", 3, 3, {WT: 2})
    b.comb(D, "wt_gate", 4, 3, conditions=[cond(PH, "≥", Tc, net=R)], outputs=[out_copy(WT, R)])
    b.arith("rst2", 5, 3, RST, "+", 0, RST)
    b.arith("lpass", 6, 3, L_SIG, "+", 0, L_SIG)
    b.comb(D, "halt", 7, 3, conditions=[cond(NL_SIG, ">", 0, net=G), cnd2(pos_sig, "≥", L_SIG)],
           outputs=[out_const(HALT, 1)])
    b.arith("dh", 8, 0, pos_sig, "-", L_SIG, DH)
    b.comb(D, "halt2", 8, 3, conditions=[cond(DH, "≥", n_reply, net=R)], outputs=[out_const(HALT, 1)])
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
    w(G, "rst2", "lpass", s1="input", s2="input")
    w(G, "rpass", "lpass2", s1="input", s2="input")
    w(G, "halt", "clk_gate", s1="output", s2="input")
    w(G, "halt2", "halt", s1="output", s2="output")
    # CTRL (red): P, W, R, L
    w(R, "pos", "w", s1="output", s2="output")
    w(R, "w", "wone", s1="output")
    w(R, "w", "rpass", s1="output", s2="output")
    w(R, "rpass", "lpass2", s1="output", s2="output")
    w(R, "lpass2", "halt", s1="output", s2="input")
    w(R, "lpass2", "dh", s1="output", s2="input")
    w(R, "dh", "halt2", s1="output", s2="input")
    # Q (red): PH, WT (+2) -> wt_gate ; TCTL (red): WT gated, RST, L
    w(R, "ph", "wt", s1="output", s2="output")
    w(R, "wt", "wttwo", s1="output")
    w(R, "wt", "wt_gate", s1="output", s2="input")
    w(R, "wt_gate", "rst2", s1="output", s2="output")
    w(R, "rst2", "lpass", s1="output", s2="output")

    # ---------------- buttons, SEND edge, latches (x 0..12, y 6..27) ----------------
    b.arith("sdel", 1, 6, SEND, "+", 0, SD)
    b.comb(D, "pulse", 2, 6, conditions=[cond(SEND, ">", 0, net=G), cond(SD, "=", 0, net=R, ct="and"),
                                         cond(HALT, ">", 0, net=G, ct="and"),
                                         cond(SEND, ">", 0, net=G, ct="or"), cond(SD, "=", 0, net=R, ct="and"),
                                         cond(RUN, "=", 0, net=G, ct="and")], outputs=[out_const(PULSE, 1)])
    b.arith("brst_rst", 3, 6, BRST, "+", 0, RST)                                 # RST on CMD = RESET + WIPE
    b.arith("brst_pl", 4, 6, BRST, "+", 0, BRST)                                 # RESET onto the PULSE net
    b.comb(D, "run_set", 5, 6, conditions=[cond(PULSE, ">", 0, net=R)], outputs=[out_const(RUN, 1)])
    b.comb(D, "run_hold", 6, 6, conditions=[cond(BRST, "=", 0, net=G)], outputs=[out_copy(RUN, G)])
    b.comb(D, "wipe", 7, 6, conditions=[cond(PULSE, ">", 0, net=R), cond(OVF, ">", 0, net=G, ct="and")],
           outputs=[out_const(RST, 1)])
    b.arith("clr", 8, 6, EACH, "+", 0, CLR)                                      # PULSE + RESET -> CLR (RCTL)
    b.const("lconst", 1, 8, {L_SIG: len(PREFIX) + len(SUFFIX)})
    # CMD membership
    w(G, "sdel", "pulse", s1="input", s2="input")
    w(G, "sdel", "brst_rst", s1="input", s2="input")
    w(G, "brst_rst", "brst_pl", s1="input", s2="input")
    w(R, "sdel", "pulse", s1="output", s2="input")               # SD (red)
    w(G, "brst_pl", "run_hold", s1="input", s2="input")
    w(G, "run_set", "run_hold", s1="output", s2="output")
    w(G, "run_hold", "run_hold", s1="output", s2="input")
    w(G, "run_hold", "wipe", s1="output", s2="output")
    w(G, "lconst", "cmd_src")
    w(G, "cmd_src", "sdel", s2="input")
    # PULSE net (red): pulse out, BRST (brst_pl red out) -> run_set, wipe, latch gate/hold, clr
    w(R, "pulse", "run_set", s1="output", s2="input")
    w(R, "run_set", "wipe", s1="input", s2="input")
    w(R, "wipe", "clr", s1="input", s2="input")
    w(R, "brst_pl", "run_set", s1="output", s2="input")
    # latches: X = P + HALT, C = filled slots (REGIN, green); Z = X + C; OK = Z <= FIT; S' = X * OK
    b.arith("xp", 0, 12, pos_sig, "+", 0, X_)
    b.arith("xh", 1, 12, HALT, "+", 0, X_)
    b.arith("z", 2, 12, X_, "+", CNT, Z_, G, G)
    b.comb(D, "ok", 3, 12, conditions=[cond(Z_, "≤", FIT, net=R)], outputs=[out_const(OK_, 1)])
    b.comb(D, "ovf", 4, 12, conditions=[cond(Z_, ">", FIT, net=R)], outputs=[out_const(OVF, 1)])
    b.arith("snew", 5, 12, X_, "*", OK_, SS, G, R)
    b.comb(D, "lgate", 6, 12, conditions=[cond(PULSE, ">", 0, net=R)], outputs=[out_copy(SS, G), out_copy(CNT, G)])
    b.comb(D, "lhold", 7, 12, conditions=[cond(PULSE, "=", 0, net=R), cond(BRST, "=", 0, net=R, ct="and")],
           outputs=[out_copy(SS, G), out_copy(CNT, G)])
    b.arith("lsum", 8, 12, EACH, "+", 0, L_SIG)                                  # L = S + C (+11 lconst)
    w(R, "lpass2", "xp", s1="output", s2="input")                                # CTRL -> xp
    w(G, "halt", "xh", s1="output", s2="input")                                  # CMD -> xh
    w(G, "xp", "xh", s1="output", s2="output")                                   # REGIN (green)
    w(G, "xh", "z", s1="output", s2="input")
    w(G, "z", "snew", s1="input", s2="input")
    w(G, "snew", "snew", s1="output", s2="input")
    w(G, "snew", "lgate", s1="input", s2="input")
    w(R, "z", "ok", s1="output", s2="input")
    w(R, "ok", "ovf", s1="input", s2="input")
    w(R, "ok", "snew", s1="output", s2="input")                                  # OK (red)
    w(G, "ovf", "wipe", s1="output", s2="input")                                 # OVF (green)
    w(R, "run_set", "lgate", s1="input", s2="input")                             # PULSE net
    w(R, "lgate", "lhold", s1="input", s2="input")
    w(G, "lgate", "lhold", s1="output", s2="input")                              # REG (green)
    w(G, "lhold", "lhold", s1="output", s2="input")
    w(G, "lhold", "lsum", s1="output", s2="input")
    w(G, "lsum", "lconst", s1="output")                                          # L -> CMD
    w(G, "wipe", "brst_rst", s1="output", s2="output")
    w(G, "brst_rst", "lsum", s1="output", s2="output")
    w(G, "lsum", "run_hold", s1="output", s2="input")
    # QCTL (red): I = P - S, Q = C, J = I - Q
    b.arith("ip", 0, 16, pos_sig, "+", 0, I_)
    b.arith("is", 1, 16, SS, "*", -1, I_)
    b.arith("qc", 2, 16, CNT, "+", 0, Q_)
    b.arith("j", 3, 16, I_, "-", Q_, J_)
    w(R, "xp", "ip", s1="input", s2="input")                                     # CTRL
    w(G, "lhold", "is", s1="output", s2="input")                                 # REG
    w(G, "is", "qc", s1="input", s2="input")
    w(R, "ip", "is", s1="output", s2="output")
    w(R, "is", "qc", s1="output", s2="output")
    w(R, "qc", "j", s1="output", s2="input")
    w(R, "j", "j", s1="output", s2="input")
    # prefix / suffix deciders -> QT (green)
    qt = []
    for t, ch in enumerate(PREFIX):
        e = f"pre{t}"
        b.comb(D, e, 4 + t, 16, conditions=[cond(I_, "=", t, net=R)], outputs=[out_const(VOCAB_SIGS[CHARS.index(ch)], 1)])
        qt.append(e)
    for t, ch in enumerate(SUFFIX):
        e = f"suf{t}"
        b.comb(D, e, 4 + t, 18 + 2 * (t // 6), conditions=[cond(J_, "=", len(PREFIX) + t, net=R)],
               outputs=[out_const(VOCAB_SIGS[CHARS.index(ch)], 1)])
        qt.append(e)
    prev = "j"
    for e in qt:
        w(R, prev, e, s1="input", s2="input")
        prev = e
    for a, c in zip(qt, qt[1:]):
        w(G, a, c, s1="output", s2="output")
    # RCTL (red): Y = WT - L (TCTL), E = PULSE + RESET
    b.arith("wr", 9, 0, WT, "-", L_SIG, WR)
    w(R, "lpass", "wr", s1="output", s2="input")                                 # TCTL
    w(R, "clr", "wr", s1="output", s2="output")
    # progress bar: B = (I + 1) * 30 / (Q + 11) while RUN; colour by B
    b.arith("ba", 10, 12, I_, "+", 1, "signal-A")
    b.arith("bd", 11, 12, Q_, "+", len(PREFIX) + len(SUFFIX), "signal-G")
    b.arith("bm", 10, 14, "signal-A", "*", 30, "signal-M")
    b.arith("bdp", 11, 14, "signal-G", "+", 0, "signal-G")
    b.arith("bq", 12, 14, "signal-M", "/", "signal-G", BAR)
    b.comb(D, "bgate", 12, 12, conditions=[cond(RUN, ">", 0, net=G)], outputs=[out_copy(BAR, R)])
    w(R, "j", "ba", s1="input", s2="input")
    w(R, "ba", "bd", s1="input", s2="input")
    w(R, "ba", "bm", s1="output", s2="input")
    w(R, "bd", "bdp", s1="output", s2="input")
    w(R, "bm", "bq", s1="output", s2="input")
    w(R, "bdp", "bq", s1="output", s2="input")
    w(R, "bq", "bgate", s1="output", s2="input")
    w(G, "run_hold", "bgate", s1="input", s2="input")                            # CMD
    # BARNET (red) = bgate out + colour deciders (inputs and outputs) + lamps: colour by the bar length
    for k, (lo, hi, col) in enumerate(((1, 10, "signal-red"), (11, 20, "signal-yellow"), (21, 10 ** 9, "signal-green"))):
        b.comb(D, f"bc{k}", 13 + k, 12, conditions=[cond(BAR, "≥", lo, net=R), cond(BAR, "≤", hi, net=R, ct="and")],
               outputs=[out_const(col, 1)])
        w(R, "bgate", f"bc{k}", s1="output", s2="input")
        w(R, "bgate", f"bc{k}", s1="output", s2="output")
    for k in range(30):
        _lamp(b, f"bar{k}", XQ + k, YQ + 16, BAR, k + 1, use_colors=True)
        w(R, "bc2" if k == 0 else f"bar{k - 1}", f"bar{k}", s1="output" if k == 0 else None)

    # ---------------- query console: 100 slots side by side (x = XS + k, y = YS), one 1-tile column each --------
    # column k under slot k: kc (signals in the slot) -> stop (empty or END -> STOP_k = k+1), tok (token for
    # the model), norm (letter -> 1 if k < CL), d1 / d2 (font masks G1_k / G2_k onto the shared BUS).
    # Length C = first stop (selector min over the stop signals, cfull = 101 when every slot is filled).
    # The board's query cells read only their own G1_k / G2_k from the BUS: s1, s2, AND and 35 lamps.
    c1 = {VOCAB_SIGS[i]: codes(ch)[0] for i, ch in enumerate(CHARS) if codes(ch)[0]}
    c2 = {VOCAB_SIGS[i]: codes(ch)[1] for i, ch in enumerate(CHARS) if codes(ch)[1]}
    b.comb(SelectorCombinator, "cmin", 14, YS - 8, operation="select", select_max=False, index_constant=0)
    b.arith("cminus", 15, YS - 8, EACH, "+", -1, CNT)
    b.arith("clive", 16, YS - 8, EACH, "+", -1, CL)
    b.const("cfull", 17, YS - 8, {STOP[n_query]: n_query + 1})
    w(R, "cmin", "cfull", s1="input")
    w(R, "cmin", "cminus", s1="output", s2="input")
    w(R, "cminus", "clive", s1="input", s2="input")
    b.const("qcode1", XS - 2, YS + 9, c1)
    b.const("qcode2", XS - 2, YS + 11, c2)
    for m in range(0, n_query + 17, 18):
        xm = XS + min(m, n_query - 2)
        b.substation(f"ssub_a{m}", xm + (2 if m == 0 else 0), YS - 3)
        b.substation(f"ssub_b{m}", xm, YS + 13)
    for k in range(n_query):
        x, t = XS + k, f"q{k}_"
        b.const(t + "slot", x, YS, {})
        b.arith(t + "kc", x, YS + 1, EACH, "/", EACH, KC, G, G)
        b.comb(D, t + "stop", x, YS + 3, conditions=[cond(KC, "=", 0, net=R), cond(END, ">", 0, net=G, ct="or")],
               outputs=[out_const(STOP[k], k + 1)])
        b.comb(D, t + "tok", x, YS + 5, conditions=[cond(I_, "=", len(PREFIX) + k, net=R), cond(Q_, ">", k, net=R, ct="and")],
               outputs=[out_copy(EVERYTHING, G)])
        b.comb(D, t + "norm", x, YS + 7, conditions=[cond(EACH, ">", 0, net=G), cond(CL, ">", k, net=R, ct="and")],
               outputs=[out_const(EACH, 1)])
        b.arith(t + "d1", x, YS + 9, EACH, "*", EACH, G1[k], R, G)
        b.arith(t + "d2", x, YS + 11, EACH, "*", EACH, G2[k], R, G)
        w(G, t + "slot", t + "kc", s2="input")
        w(G, t + "kc", t + "stop", s1="input", s2="input")
        w(R, t + "kc", t + "stop", s1="output", s2="input")
        w(G, t + "stop", t + "tok", s1="input", s2="input")
        w(G, t + "tok", t + "norm", s1="input", s2="input")
        w(R, t + "norm", t + "d1", s1="output", s2="input")
        w(R, t + "d1", t + "d2", s1="input", s2="input")
        w(R, t + "d1", t + "d2", s1="output", s2="output")                     # BUS
        if k == 0:
            w(G, "qcode1", t + "d1", s2="input")
            w(G, "qcode2", t + "d2", s2="input")
        else:
            p = f"q{k - 1}_"
            w(R, p + "stop", t + "stop", s1="output", s2="output")
            w(R, p + "tok", t + "tok", s1="input", s2="input")
            w(G, p + "tok", t + "tok", s1="output", s2="output")
            w(R, p + "norm", t + "norm", s1="input", s2="input")
            w(G, p + "d1", t + "d1", s1="input", s2="input")                     # CODE1
            w(G, p + "d2", t + "d2", s1="input", s2="input")                     # CODE2
            w(R, p + "d1", t + "d1", s1="output", s2="output")                   # BUS
    # SEND / RESET buttons at the start of the strip, one row above it, with labels above them
    b.const("send", XS, YS - 1, {SEND: 1}, on=False)
    b.const("reset", XS + 1, YS - 1, {BRST: 1}, on=False)
    b.entity(DisplayPanel, "send_lbl", XS, YS - 2, 1, 1, text="ОТПРАВИТЬ / SEND / 发送", icon="signal-input",
             always_show_in_alt_mode=True, show_in_chart=True)
    b.entity(DisplayPanel, "reset_lbl", XS + 1, YS - 3, 1, 1, text="СБРОС / RESET / 重置", icon="signal-alert",
             always_show_in_alt_mode=True, show_in_chart=True)
    # instructions: one column of display panels per language above the strip
    for li, lines in enumerate(INSTRUCTIONS):
        n = len(lines)
        for si, (icon, text) in enumerate(lines):
            kw = dict(icon=icon) if icon else {}
            b.entity(DisplayPanel, f"help{li}_{si}", XS + 6 + 40 * li, YS - 6 - 2 * (n - 1 - si), 1, 1, text=text,
                     always_show_in_alt_mode=True, show_in_chart=False, **kw)
    w(G, "send", "reset")
    w(G, "send", "sdel", s2="input")                                              # -> CMD (pole route)
    B.link(G, b.id("xh"), "output", b.id("cminus"), "output", b.id("regin"))       # REGIN <- length
    B.link(R, b.id("cmin"), "input", b.id("q0_stop"), "output", b.id("stops"))     # stop signals
    B.link(R, b.id("clive"), "output", b.id("q0_norm"), "input", b.id("cl"))       # CL
    B.link(R, b.id("j"), "input", b.id("q0_tok"), "input", b.id("qctl"))           # QCTL -> columns
    B.link(G, b.id(qt[-1]), "output", b.id("q0_tok"), "output", b.id("qtl"))       # QT

    # query line of the board: per character s1 = G1_k >> each(SH1), s2 = G2_k >> each(SH2), AND 1 -> lamps
    b.const("qsh1", XQ - 2, YQ, {PIX[p]: shift(p) for p in range(20)})
    b.const("qsh2", XQ - 1, YQ, {PIX[p]: shift(p) for p in range(20, 35)})
    order = [(r, c if r % 2 == 0 else FW - 1 - c) for r in range(FH) for c in range(FW)]
    for k in range(n_query):
        x, t = XQ + 6 * k, f"qd{k}_"
        b.arith(t + "s1", x, YQ, G1[k], ">>", EACH, EACH, R, G)
        b.arith(t + "s2", x + 1, YQ, G2[k], ">>", EACH, EACH, R, G)
        b.arith(t + "and", x + 2, YQ, EACH, "AND", 1, EACH, R)
        w(R, t + "s1", t + "s2", s1="input", s2="input")                         # BUS
        w(R, t + "s1", t + "s2", s1="output", s2="output")
        w(R, t + "s2", t + "and", s1="output", s2="input")
        prev, prev_side = t + "and", "output"
        for r, c in order:
            pp = r * FW + c
            lid = f"{t}px{pp}"
            _lamp(b, lid, x + c, YQ + 6 + r, PIX[pp], 0, color=qcol)
            w(R, prev, lid, s1=prev_side)
            prev, prev_side = lid, None
        if k == 0:
            w(G, "qsh1", t + "s1", s2="input")
            w(G, "qsh2", t + "s2", s2="input")
        else:
            p = f"qd{k - 1}_"
            w(R, p + "s1", t + "s1", s1="input", s2="input")
            w(G, p + "s1", t + "s1", s1="input", s2="input")                     # SH1
            w(G, p + "s2", t + "s2", s1="input", s2="input")                     # SH2
        if k % 3 == 0 or k == n_query - 1:
            b.substation(f"qsub{k}", x, YQ + 4)
    B.link(R, b.id("q0_d1"), "output", b.id("qd0_s1"), "input", b.id("bus"))       # BUS -> board

    # ---------------- reply line: sample-and-hold cell + glyph ----------------
    prev_tables = None
    for i in range(n_reply):
        x, t = XR + 6 * i, f"r{i}_"
        b.comb(D, t + "gate", x, YR, conditions=[cond(WR, "=", i + 1, net=R)], outputs=[out_copy(EVERYTHING, G)])
        b.comb(D, t + "hold", x + 1, YR, conditions=[cond(WR, "!=", i + 1, net=R), cond(CLR, "=", 0, net=R, ct="and")],
               outputs=[out_copy(EVERYTHING, G)])
        w(G, t + "gate", t + "hold", s1="output", s2="input")
        w(G, t + "hold", t + "hold", s1="output", s2="input")
        w(R, t + "gate", t + "hold", s1="input", s2="input")
        tabs = _glyph_cell(b, t, x, YR, YR + 6, (t + "hold", "output"), rcol,
                           ((2, YR), (3, YR), (4, YR), (5, YR), (0, YR + 2)))
        if i == 0:
            _tables(b, "rt_", XR - 2, YR, YR + 2, tabs)
            B.link(R, b.id("wr"), "output", b.id(t + "gate"), "input", b.id("rctl"))
        else:
            p = f"r{i - 1}_"
            _chain_tables(b, prev_tables, tabs)
            w(R, p + "gate", t + "gate", s1="input", s2="input")                 # RCTL
            w(G, p + "gate", t + "gate", s1="input", s2="input")                 # NEXT
        prev_tables = tabs
        if i % 3 == 0 or i == n_reply - 1:
            b.substation(f"rsub{i}", x, YR + 4)

    # ---------------- token cells (generated tokens) ----------------
    gates = []
    for j in range(ctx):
        x = XQ + j
        b.comb(D, f"gate_{j}", x, YT, conditions=[cond(WT, "=", j + 1, net=R), cond(L_SIG, "≤", j, net=R, ct="and")],
               outputs=[out_copy(EVERYTHING, G)])
        b.comb(D, f"hold_{j}", x, YT + 2, conditions=[cond(WT, "!=", j + 1, net=R), cond(RST, "=", 0, net=R, ct="and")],
               outputs=[out_copy(EVERYTHING, G)])
        b.comb(D, f"mux_{j}", x, YT + 4, conditions=[cond(pos_sig, "=", j, net=R)], outputs=[out_copy(EVERYTHING, G)])
        w(G, f"gate_{j}", f"hold_{j}", s1="output", s2="input")
        w(G, f"hold_{j}", f"hold_{j}", s1="output", s2="input")
        w(R, f"gate_{j}", f"hold_{j}", s1="input", s2="input")
        w(G, f"hold_{j}", f"mux_{j}", s1="input", s2="input")
        if j:
            w(R, f"gate_{j - 1}", f"gate_{j}", s1="input", s2="input")
            w(G, f"gate_{j - 1}", f"gate_{j}", s1="input", s2="input")
            w(R, f"mux_{j - 1}", f"mux_{j}", s1="input", s2="input")
            w(G, f"mux_{j - 1}", f"mux_{j}", s1="output", s2="output")
        gates.append(f"gate_{j}")
        if j % 10 == 0:
            b.substation(f"tsub{j}", x, YT + 6)
    B.link(R, b.id("rst2"), "output", b.id("gate_0"), "input", b.id("tctl"))         # TCTL -> cells
    B.link(R, b.id("lpass2"), "output", b.id("mux_0"), "input", b.id("ctlmux"))      # CTRL -> muxes
    B.link(G, b.id("mux_0"), "output", b.id("halt"), "input", b.id("tokhalt"))       # TOKEN -> halt
    B.link(G, b.id(qt[0]), "output", b.id("mux_0"), "output", b.id("qttok"))         # QT -> TOKEN
    B.link(G, b.id("gate_0"), "input", b.id("r0_gate"), "input", b.id("nextr"))     # NEXT -> reply gates
    return dict(ctrl=[(b.id("pos"), "output")], token=[(b.id(f"mux_{j}"), "output") for j in range(ctx)],
                next=[(b.id(g), "input") for g in gates], cmd=b.id("cmd_src"), send=b.id("send"), reset=b.id("reset"),
                slots=[b.id(f"q{k}_slot") for k in range(n_query)], reply=[b.id(f"r{i}_hold") for i in range(n_reply)],
                clock=b.id("clk_acc"))
