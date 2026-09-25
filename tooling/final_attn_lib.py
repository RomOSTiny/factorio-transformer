"""Causal attention with a KV cache for the FINAL model (d=256, 8 heads, ctx 256), Factorio 2.0 vector
combinators. Semantics: final_ref.IntModel.attention (exact).

Same structure as dense_attn_lib (P3, verified live), changed for the delivered model's engine rounding:
  score   raw'_j = q_h . k_j + OFF              each(red QH_h) * each(green KCELL_j) -> key_j (no division:
                                                the exp buckets are integer thresholds on q.k itself)
  max     M = max_j raw'_j                     selector; u_j = (M + 1) - raw'_j = delta_j + 1 >= 1
  exp     e_j = sum_t [u_j <= T_t + 1] * d_t   decider bank = final_ref exp_steps (134 steps, e in 2e5 units)
  softmax S = sum_j e_j ; w_j = e_j * 1e4 / S  (each+0 -> S ; each*1e4 ; each(green)/S(red))
  out     att = (sum_j w_j v_j)(.)mask_h / 1e4
Ports: QNET red (q), KNET green (k), VNET green (v), CTL red (W = cell+1 writes, R clears), ATT red (att).

Layout (north-facing 1x2 combinators, cell row j at y = row_y(j)):
  x=0 k gate, x=1 k hold, x=2..9 score column per head          (K half)
  x=11..15 head pipelines, head h in rows RPH*h .. RPH*h+RPH-1  (RPH = n_cells / heads = 32)
  x=17 v gate, x=18 v hold, x=19..26 weighted-sum column per head (V half)
  header above row 0 (y 4..9): q / att filters with head masks, V constants, CTL poles, test ports.
"""
import math

from draftsman.entity import DeciderCombinator, SelectorCombinator

from circuit_builder import EACH, EVERYTHING, G, R, Sub, cond as _cond

V_SIG, M_SIG, S_SIG, W_SIG, R_SIG = "signal-V", "signal-M", "signal-S", "signal-W", "signal-R"
SPECIAL = {V_SIG, M_SIG, S_SIG, W_SIG, R_SIG}

TOP = 10
ROWS_PER_GROUP = 4
STRIP_STEP = 10
KG, KH, SC0 = 0, 1, 2
PIPE_X0, PIPE_W = 11, 5
VG, VH, WS0 = 17, 18, 19
SUB_XS = (5, 14, 23)
W_SCALE = 10000             # attention weights in 1e-4


def row_y(j):
    g, r = divmod(j, ROWS_PER_GROUP)
    return TOP + g * STRIP_STEP + 2 + r * 2


def size(n_cells):
    return WS0 + 9, row_y(n_cells - 1) + 3


def place_final_attn(B, pfx, ox, oy, dims, keys, steps, off, heads=8, n_cells=256, test_ports=False):
    """steps: [(T, d)] from final_ref.IntModel.exp_steps() (e = sum [delta <= T] d), off: score offset."""
    dim = len(dims)
    hd_n = dim // heads
    rph = n_cells // heads
    assert len(keys) == n_cells and n_cells % heads == 0 and heads <= 8
    used = set(dims) | set(keys)
    assert len(used) == dim + n_cells and not (used & SPECIAL), "signal clash"
    b = Sub(B, pfx, ox, oy)
    masks = [{dims[d]: 1 for d in range(h * hd_n, (h + 1) * hd_n)} for h in range(heads)]

    # ---- grid of KV cells, scores and weighted sums ----
    for j in range(n_cells):
        y = row_y(j)
        kg, kh, vg, vh = f"kg_{j}", f"kh_{j}", f"vg_{j}", f"vh_{j}"
        for gate, hold, gx, hx in ((kg, kh, KG, KH), (vg, vh, VG, VH)):
            b.comb(DeciderCombinator, gate, gx, y, conditions=[_cond(W_SIG, "=", j + 1, R)],
                   outputs=[DeciderCombinator.Output(signal=EVERYTHING, copy_count_from_input=True, networks={G})])
            b.comb(DeciderCombinator, hold, hx, y,
                   conditions=[_cond(W_SIG, "!=", j + 1, R), _cond(R_SIG, "=", 0, R, ct="and")],
                   outputs=[DeciderCombinator.Output(signal=EVERYTHING, copy_count_from_input=True, networks={G})])
            b.wire(G, gate, hold, s1="output", s2="input")
            b.wire(G, hold, hold, s1="output", s2="input")
            b.wire(R, gate, hold, s1="input", s2="input")
            if j > 0:
                b.wire(R, f"{gate[:2]}_{j - 1}", gate, s1="input", s2="input")    # CTL
                b.wire(G, f"{gate[:2]}_{j - 1}", gate, s1="input", s2="input")    # KNET / VNET
        prev_s, prev_w = kh, vh
        for h in range(heads):
            s, w = f"sc_{h}_{j}", f"ws_{h}_{j}"
            b.arith(s, SC0 + h, y, EACH, "*", EACH, keys[j], R, G)
            b.arith(w, WS0 + h, y, EACH, "*", keys[j], EACH, G, R)
            b.wire(G, prev_s, s, s1="input", s2="input")                           # KCELL_j
            b.wire(G, prev_w, w, s1="input", s2="input")                           # VCELL_j
            prev_s, prev_w = s, w
            if j > 0:
                b.wire(R, f"sc_{h}_{j - 1}", s, s1="input", s2="input")            # QH_h
                b.wire(R, f"sc_{h}_{j - 1}", s, s1="output", s2="output")          # SC_h
                b.wire(R, f"ws_{h}_{j - 1}", w, s1="input", s2="input")            # W_h
                b.wire(R, f"ws_{h}_{j - 1}", w, s1="output", s2="output")          # AT_h

    # ---- head pipelines ----
    exp_slots = [(PIPE_X0 + (c if ri % 2 == 0 else PIPE_W - 1 - c), ri) for ri in range(2, rph - 2) for c in range(PIPE_W)]
    assert len(steps) <= len(exp_slots), f"{len(steps)} exp steps > {len(exp_slots)} slots"
    X0 = PIPE_X0
    for h in range(heads):
        j0 = rph * h
        p = f"p{h}_"
        b.arith(p + "pass", X0, row_y(j0), EACH, "+", 0, EACH)
        b.comb(SelectorCombinator, p + "sel", X0 + 1, row_y(j0), operation="select", select_max=True, index_constant=0)
        b.arith(p + "msum", X0 + 2, row_y(j0), EACH, "+", 0, M_SIG)
        b.const(p + "mc", X0 + 3, row_y(j0), {M_SIG: 1})
        b.arith(p + "u", X0, row_y(j0 + 1), M_SIG, "-", EACH, EACH, R, G)
        near_sc = min(range(j0, j0 + rph), key=lambda j: math.dist(b.pos[f"sc_{h}_{j}"], b.pos[p + "pass"]))
        B.link(R, b.id(f"sc_{h}_{near_sc}"), "output", b.id(p + "pass"), "input", b.id(p + "scl"))   # SC_h in
        b.wire(R, p + "pass", p + "sel", s1="output", s2="input")
        b.wire(G, p + "pass", p + "u", s1="output", s2="input")                     # SC (green) -> u
        b.wire(R, p + "sel", p + "msum", s1="output", s2="input")
        b.wire(R, p + "msum", p + "mc", s1="output")
        b.wire(R, p + "msum", p + "u", s1="output", s2="input")                     # M+1 (red) -> u
        prev = None
        for t, (thr, d) in enumerate(steps):
            x, ri = exp_slots[t]
            e = f"{p}e{t}"
            b.comb(DeciderCombinator, e, x, row_y(j0 + ri), conditions=[_cond(EACH, "<=", thr + 1)],
                   outputs=[DeciderCombinator.Output(signal=EACH, copy_count_from_input=False, constant=d)])
            if prev is None:
                b.wire(R, p + "u", e, s1="output", s2="input")                      # U (red)
            else:
                b.wire(R, prev, e, s1="input", s2="input")
                b.wire(G, prev, e, s1="output", s2="output")                        # E (green)
            prev = e
        ry = row_y(j0 + rph - 2)
        b.arith(p + "ssum", X0, ry, EACH, "+", 0, S_SIG)
        b.arith(p + "x1e4", X0 + 2, ry, EACH, "*", W_SCALE, EACH)
        b.arith(p + "wdiv", X0 + 4, ry, EACH, "/", S_SIG, EACH, G, R)
        for tgt in ("ssum", "x1e4"):
            en = min((f"{p}e{t}" for t in range(len(steps))), key=lambda k: math.dist(b.pos[k], b.pos[p + tgt]))
            b.wire(G, en, p + tgt, s1="output", s2="input")                         # E -> S, E*1e4
        b.wire(G, p + "x1e4", p + "wdiv", s1="output", s2="input")
        b.wire(R, p + "ssum", p + "wdiv", s1="output", s2="input")                  # S (red)
        near_ws = min(range(j0, j0 + rph), key=lambda j: math.dist(b.pos[f"ws_{h}_{j}"], b.pos[p + "wdiv"]))
        B.link(R, b.id(p + "wdiv"), "output", b.id(f"ws_{h}_{near_ws}"), "input", b.id(p + "wl"))  # W_h out

    # ---- header: q filters, att filters, V constants, CTL, ports ----
    hy = TOP - 4
    b.const("qv_const", 1, hy, {V_SIG: 1})
    b.const("kv_const", KG, hy + 2, {V_SIG: off})
    b.wire(G, "kv_const", "kg_0", s2="input")                                      # KNET gets V=OFF
    for h in range(heads):
        qf, qm, af, am = f"qf_{h}", f"qm_{h}", f"af_{h}", f"am_{h}"
        b.arith(qf, SC0 + h, hy, EACH, "*", EACH, EACH, R, G)
        b.const(qm, SC0 + h, hy - 2, {**masks[h], V_SIG: 1})
        b.wire(G, qm, qf, s2="input")
        b.wire(R, qf, f"sc_{h}_0", s1="output", s2="input")                         # QH_h
        b.wire(R, "qv_const" if h == 0 else f"qf_{h - 1}", qf, s1=None if h == 0 else "input", s2="input")   # QNET
        b.arith(af, WS0 + h, hy, EACH, "*", EACH, EACH, R, G)
        b.const(am, WS0 + h, hy - 2, masks[h])
        b.wire(G, am, af, s2="input")
        b.wire(R, f"ws_{h}_0", af, s1="output", s2="input")                         # AT_h
        if h > 0:
            b.wire(R, f"af_{h - 1}", af, s1="output", s2="output")
    b.arith("att_out", WS0 + heads, hy, EACH, "/", W_SCALE, EACH)
    b.wire(R, f"af_{heads - 1}", "att_out", s1="output", s2="input")
    b.pole("ctl_pole_k", 6, TOP - 1)
    b.pole("ctl_mid", 11, TOP - 1)
    b.pole("ctl_pole", 16, TOP - 1)
    b.wire(R, "ctl_pole", "ctl_mid")
    b.wire(R, "ctl_mid", "ctl_pole_k")
    b.wire(R, "ctl_pole_k", "kg_0", s2="input")
    b.wire(R, "ctl_pole", "vg_0", s2="input")
    if test_ports:
        b.const("q_src", 1, hy - 2, {})
        b.wire(R, "q_src", "qv_const")
        b.const("k_src", KG, hy - 2, {})
        b.wire(G, "k_src", "kv_const")
        b.const("v_src", VG, hy, {})
        b.wire(G, "v_src", "vg_0", s2="input")
        b.const("ctl_src", 4, TOP - 1, {})
        b.wire(R, "ctl_src", "ctl_pole_k")
        b.const("att_sink", WS0 + heads, hy - 2, {})
        b.wire(R, "att_out", "att_sink", s1="output")

    # ---- power ----
    n_groups = math.ceil(n_cells / ROWS_PER_GROUP)
    for g in range(n_groups + 1):
        for x in SUB_XS:
            b.substation(f"sub_{g}_{x}", x, TOP + g * STRIP_STEP)
        for x0, x1 in zip(SUB_XS, SUB_XS[1:]):
            b.power(f"sub_{g}_{x0}", f"sub_{g}_{x1}")
        if g > 0:
            for x in SUB_XS:
                b.power(f"sub_{g - 1}_{x}", f"sub_{g}_{x}")
    return dict(q_in=b.id("qv_const"), k_in=[b.id(f"kg_{j}") for j in range(n_cells)],
                v_in=[b.id(f"vg_{j}") for j in range(n_cells)], ctl=b.id("ctl_pole"), att_out=b.id("att_out"))
