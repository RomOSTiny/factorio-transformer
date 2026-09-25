"""Dense causal attention with a KV cache for one layer (P3), built from Factorio 2.0 vector combinators.

Math and integer semantics: attn_kv_ref.attn_step (this generator must match it exactly).

Ports (networks the rest of the model attaches to):
  QNET  red    q_i on DIM signals            -> q filters (header, x=2..5)
  KNET  green  k_i on DIM signals            -> k gates column (x=0); the block adds V=OFF on it
  VNET  green  v_i on DIM signals            -> v gates column
  CTL   red    W = cell+1 to write (level, sample-and-hold), R != 0 clears all cells
  ATT   red    att_i on DIM signals          <- att_out combinator output

Layout (north-facing 1x2 combinators, cell row j at y = row_y(j), 4 rows per power group):
  x=0 k gate, x=1 k hold, x=2..5 score column per head   (K half)
  x=7..11 head pipelines, head h in rows 12h..12h+11      (middle)
  x=13 v gate, x=14 v hold, x=15..18 weighted-sum column per head (V half)
  header above row 0: q filters / att filters with their head masks, V constants, ports.
Networks per head h:
  QH_h  = q (.) mask_h + V=1          red down score column h (input side)
  KCELL_j = k_j + V=OFF                green across row j (k hold input, score inputs)
  SC_h  = raw'_j on KEYS[j]            red down score column h (output side) -> pipeline
  pipeline: div(/DIVQ) -> selector max -> each+0 -> M (+const 1) -> u = M - each
            -> exp step deciders (each <= thr -> each = SCALE*delta) -> E (green)
            -> S = each/SCALE ; w = each(E)/S -> W_h red up weighted-sum column h (input side)
  VCELL_j = v_j                        green across row j (v hold input, weighted-sum inputs)
  AT_h  = sum_j w_j * v_j              red up weighted-sum column h (output side) -> att filter h
  ATT   = sum_h AT_h (.) mask_h / SCALE
"""
import math

from draftsman.entity import DeciderCombinator, SelectorCombinator

from circuit_builder import EACH, EVERYTHING, G, R, Builder, Sub, cond as _cond

V_SIG, M_SIG, S_SIG, W_SIG, R_SIG = "signal-V", "signal-M", "signal-S", "signal-W", "signal-R"
SPECIAL = {V_SIG, M_SIG, S_SIG, W_SIG, R_SIG}

TOP = 10                # first power strip; header lives above it
ROWS_PER_GROUP = 4
STRIP_STEP = 10
KG, KH, SC0 = 0, 1, 2
PIPE_X0 = 7
VG, VH, WS0 = 13, 14, 15
SUB_XS = (3, 12)


def row_y(j):
    g, r = divmod(j, ROWS_PER_GROUP)
    return TOP + g * STRIP_STEP + 2 + r * 2


def _arith(b, eid, x, y, first, op, second, out, w1=None, w2=None):
    return b.arith(eid, x, y, first, op, second, out, w1, w2)


def place_dense_attn(B, pfx, ox, oy, dims, keys, C, heads=4, n_cells=48, test_ports=False):
    """Put one attention block into Builder B (ids prefixed with pfx, local origin at (ox, oy)).

    dims: DIM signal names (q/k/v/att), keys: n_cells signal names (per-key scalars),
    C: attn_kv_ref.make_consts(...). test_ports adds driver constants q_src/k_src/v_src/ctl_src
    and an att_sink so the block can be tested standalone over RCON.
    Returns the port ids (see module docstring for the networks).
    """
    dim = len(dims)
    hd_n = dim // heads
    assert len(keys) == n_cells and n_cells % heads == 0 and n_cells // heads == 12, "pipeline bands assume 12 rows/head"
    used = set(dims) | set(keys)
    assert len(used) == dim + n_cells and not (used & SPECIAL), "signal clash"
    scale = C["scale"]
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
            _arith(b, s, SC0 + h, y, EACH, "*", EACH, keys[j], R, G)
            _arith(b, w, WS0 + h, y, EACH, "*", keys[j], EACH, G, R)
            b.wire(G, prev_s, s, s1="input", s2="input")                           # KCELL_j
            b.wire(G, prev_w, w, s1="input", s2="input")                           # VCELL_j
            prev_s, prev_w = s, w
            if j > 0:
                b.wire(R, f"sc_{h}_{j - 1}", s, s1="input", s2="input")            # QH_h
                b.wire(R, f"sc_{h}_{j - 1}", s, s1="output", s2="output")          # SC_h
                b.wire(R, f"ws_{h}_{j - 1}", w, s1="input", s2="input")            # W_h
                b.wire(R, f"ws_{h}_{j - 1}", w, s1="output", s2="output")          # AT_h

    # ---- head pipelines (middle band, rows 12h..12h+11) ----
    exp_slots = [(PIPE_X0 + (c if (ri % 2 == 0) else 4 - c), ri) for ri in range(2, 10) for c in range(5)]
    thresholds = C["thresholds"]
    assert len(thresholds) <= len(exp_slots)
    for h in range(heads):
        j0 = 12 * h
        p = f"p{h}_"
        _arith(b, p + "div", PIPE_X0, row_y(j0), EACH, "/", C["divq"], EACH)
        b.comb(SelectorCombinator, p + "sel", PIPE_X0 + 1, row_y(j0), operation="select", select_max=True, index_constant=0)
        _arith(b, p + "msum", PIPE_X0 + 2, row_y(j0), EACH, "+", 0, M_SIG)
        b.const(p + "mc", PIPE_X0 + 3, row_y(j0), {M_SIG: 1})
        _arith(b, p + "u", PIPE_X0, row_y(j0 + 1), M_SIG, "-", EACH, EACH, R, G)
        b.wire(R, f"sc_{h}_{j0}", p + "div", s1="output", s2="input")               # SC_h in
        b.wire(R, p + "div", p + "sel", s1="output", s2="input")
        b.wire(G, p + "div", p + "u", s1="output", s2="input")                      # SCD (green) -> u
        b.wire(R, p + "sel", p + "msum", s1="output", s2="input")
        b.wire(R, p + "msum", p + "mc", s1="output")
        b.wire(R, p + "msum", p + "u", s1="output", s2="input")                     # M+1 (red) -> u
        prev = None
        for t, (thr, d) in enumerate(thresholds):
            x, ri = exp_slots[t]
            e = f"{p}e{t}"
            b.comb(DeciderCombinator, e, x, row_y(j0 + ri), conditions=[_cond(EACH, "<=", thr)],
                   outputs=[DeciderCombinator.Output(signal=EACH, copy_count_from_input=False, constant=scale * d)])
            if prev is None:
                b.wire(R, p + "u", e, s1="output", s2="input")                      # U (red)
            else:
                b.wire(R, prev, e, s1="input", s2="input")
                b.wire(G, prev, e, s1="output", s2="output")                        # E (green)
            prev = e
        last_e = prev
        _arith(b, p + "ssum", PIPE_X0, row_y(j0 + 10), EACH, "/", scale, S_SIG)
        _arith(b, p + "wdiv", PIPE_X0 + 4, row_y(j0 + 10), EACH, "/", S_SIG, EACH, G, R)
        e_near_ssum = min((f"{p}e{t}" for t in range(len(thresholds))),
                          key=lambda k: math.dist(b.pos[k], b.pos[p + "ssum"]))
        e_near_wdiv = min((f"{p}e{t}" for t in range(len(thresholds))),
                          key=lambda k: math.dist(b.pos[k], b.pos[p + "wdiv"]))
        b.wire(G, e_near_ssum, p + "ssum", s1="output", s2="input")
        b.wire(G, e_near_wdiv, p + "wdiv", s1="output", s2="input")
        b.wire(R, p + "ssum", p + "wdiv", s1="output", s2="input")                  # S (red)
        b.wire(R, p + "wdiv", f"ws_{h}_{j0 + 10}", s1="output", s2="input")          # W_h out
        assert last_e

    # ---- header: q filters, att filters, V constants, ports ----
    hy = TOP - 4
    b.const("qv_const", 1, hy, {V_SIG: 1})
    b.const("kv_const", KG, hy + 2, {V_SIG: C["off"]})
    b.wire(G, "kv_const", "kg_0", s2="input")                                      # KNET gets V=OFF
    for h in range(heads):
        qf, qm, af, am = f"qf_{h}", f"qm_{h}", f"af_{h}", f"am_{h}"
        _arith(b, qf, SC0 + h, hy, EACH, "*", EACH, EACH, R, G)
        b.const(qm, SC0 + h, hy - 2, {**masks[h], V_SIG: 1})
        b.wire(G, qm, qf, s2="input")
        b.wire(R, qf, f"sc_{h}_0", s1="output", s2="input")                         # QH_h
        b.wire(R, "qv_const" if h == 0 else f"qf_{h - 1}", qf, s1=None if h == 0 else "input", s2="input")   # QNET
        _arith(b, af, WS0 + h, hy, EACH, "*", EACH, EACH, R, G)
        b.const(am, WS0 + h, hy - 2, masks[h])
        b.wire(G, am, af, s2="input")
        b.wire(R, f"ws_{h}_0", af, s1="output", s2="input")                         # AT_h
        if h > 0:
            b.wire(R, f"af_{h - 1}", af, s1="output", s2="output")
    _arith(b, "att_out", WS0 + heads, hy, EACH, "/", scale, EACH)
    b.wire(R, f"af_{heads - 1}", "att_out", s1="output", s2="input")
    b.pole("ctl_pole_k", 6, TOP - 1)
    b.pole("ctl_pole", 10, TOP - 1)
    b.wire(R, "ctl_pole", "ctl_pole_k")
    b.wire(R, "ctl_pole_k", "kg_0", s2="input")
    b.wire(R, "ctl_pole", "vg_0", s2="input")
    if test_ports:
        b.const("q_src", 1, hy - 2, {})
        b.wire(R, "q_src", "qv_const")
        b.const("k_src", KG, hy - 2, {})
        b.wire(G, "k_src", "kv_const")
        b.const("v_src", VG, hy, {})
        b.wire(G, "v_src", "vg_0", s2="input")
        b.const("ctl_src", 8, TOP - 1, {})
        b.wire(R, "ctl_src", "ctl_pole")
        b.const("att_sink", WS0 + heads, hy - 2, {})
        b.wire(R, "att_out", "att_sink", s1="output")

    # ---- power ----
    n_groups = math.ceil(n_cells / ROWS_PER_GROUP)
    for g in range(n_groups):
        for x in SUB_XS:
            b.pole(f"sub_{g}_{x}", x, TOP + g * STRIP_STEP, name="substation", size=2, quality="legendary")
        b.power(f"sub_{g}_{SUB_XS[0]}", f"sub_{g}_{SUB_XS[1]}")
        if g > 0:
            for x in SUB_XS:
                b.power(f"sub_{g - 1}_{x}", f"sub_{g}_{x}")
    return dict(q_in=b.id("qv_const"), k_in=[b.id(f"kg_{j}") for j in range(n_cells)],
                v_in=[b.id(f"vg_{j}") for j in range(n_cells)], ctl=b.id("ctl_pole"), att_out=b.id("att_out"))


def build_dense_attn(label, dims, keys, C, heads=4, n_cells=48, test_ports=True):
    """Standalone test blueprint of one attention block. Returns (bp_string, idmap, meta)."""
    B = Builder(label)
    place_dense_attn(B, "", 0, 0, dims, keys, C, heads, n_cells, test_ports)
    B.eei(20, TOP)
    bp_string, idmap = B.result()
    meta = dict(entities=len(B.ents), cells=n_cells, heads=heads, exp_steps=len(C["thresholds"]),
                combinators=sum(1 for n in B.names.values() if "combinator" in n))
    return bp_string, idmap, meta
