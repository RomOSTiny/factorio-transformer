"""Newton LayerNorm component (P3.5): ~45 entities instead of the 4.4K-entity rsqrt-ROM LayerNorm.

Math and integer semantics: ln_newton_ref.layernorm_row (must match exactly).
place_newton_ln(b, pfx, ox, oy, gq, bq, in_sigs, out_sigs, C) puts the block into a Builder with its
top-left tile at (ox, oy); footprint x 0..7, y 0..9 (plus an optional substation at (8, 5)).
Ports:
  XIN  red   input vector (in_sigs)   -> {pfx}xk / {pfx}sum / {pfx}sq inputs (red)
  OUT  red   output vector (out_sigs) <- {pfx}out output (red), beta constant on it
Zero elements: a 0 element is absent from XIN, so `each - F` would skip it (dx must be -mean).
xk = each(XIN) + each(kvec = K on every dim) makes every element present; dx = xk - (F + K).
in_sigs == out_sigs is allowed (the block never mixes them on one network). Internal scalars
(E G F H Q D V S T) live on private networks only.
Layout (relative):
  y=0  xk  dx  x1000  norm  gam  out | gamma(6,0) beta(7,0) kvec(6,1) fk(7,1)
  y=2  sum  sq  mean  esq  m2  var  vp | veps(7,2) sone(7,3)
  y=4  a1 b1 a2 b2 a3 b3 a4 b4        Newton: a = V/S -> T, b = each/2 -> S
  y=6  s0 deciders k=1..8 ; y=8 k=9..15   V >= 4^k -> S = 2^(k-1)
"""
from draftsman.entity import DeciderCombinator

from circuit_builder import EACH, G, R, cond, out_const

E_, G_, F_, H_, Q_, D_, V_, S_, T_ = ("signal-E", "signal-G", "signal-F", "signal-H", "signal-Q", "signal-D",
                                      "signal-V", "signal-S", "signal-T")
K_OFF = 1_000_000       # > max |x|: x + K is never 0


def place_newton_ln(b, pfx, ox, oy, gq, bq, in_sigs, out_sigs, C, power=True):
    dim, scale = C["dim"], C["scale"]
    assert len(in_sigs) == len(out_sigs) == dim == len(gq) == len(bq)
    assert in_sigs == out_sigs, "gamma is an elementwise product: output signals are the input signals"
    n_iter, k_max = C["n_iter"], C["k_max"]
    assert n_iter <= 4 and k_max <= 16
    P = lambda s: pfx + s
    A = lambda eid, x, y, *a, **k: b.arith(P(eid), ox + x, oy + y, *a, **k)

    # front: sums, mean, variance, v
    A("sum", 0, 2, EACH, "+", 0, E_)
    A("sq", 1, 2, EACH, "*", EACH, G_)
    A("mean", 2, 2, E_, "/", dim, F_)
    A("esq", 3, 2, G_, "/", dim, H_)
    A("m2", 4, 2, F_, "*", F_, Q_)
    A("var", 5, 2, H_, "-", Q_, D_)
    A("vp", 6, 2, D_, "*", C["ln_p"], V_)
    b.const(P("veps"), ox + 7, oy + 2, {V_: C["eps_p"]})
    b.const(P("sone"), ox + 7, oy + 3, {S_: 1})
    # s0 bank
    for k in range(1, k_max + 1):
        x, y = (k - 1, 6) if k <= 8 else (k - 9, 8)
        b.comb(DeciderCombinator, P(f"s0_{k}"), ox + x, oy + y, conditions=[cond(V_, "≥", 4 ** k)],
               outputs=[out_const(S_, 2 ** (k - 1))])
    # Newton iterations
    for i in range(1, n_iter + 1):
        A(f"a{i}", 2 * (i - 1), 4, V_, "/", S_, T_)
        A(f"b{i}", 2 * (i - 1) + 1, 4, EACH, "/", 2, S_)
    # back: x + K (all dims present), dx, scale, normalize, gamma, rescale
    A("xk", 0, 0, EACH, "+", EACH, EACH, R, G)
    A("dx", 1, 0, EACH, "-", F_, EACH, R, G)
    A("x1000", 2, 0, EACH, "*", scale * C["rt"], EACH)
    A("norm", 3, 0, EACH, "/", S_, EACH, R, G)
    A("gam", 4, 0, EACH, "*", EACH, EACH, R, G)
    A("out", 5, 0, EACH, "/", scale, EACH)
    b.const(P("gamma"), ox + 6, oy, {s: int(g) for s, g in zip(in_sigs, gq) if g})
    b.const(P("beta"), ox + 7, oy, {s: int(v) for s, v in zip(out_sigs, bq) if v})
    b.const(P("kvec"), ox + 6, oy + 1, {s: K_OFF for s in in_sigs})
    b.const(P("fk"), ox + 7, oy + 1, {F_: K_OFF})

    w = b.wire
    # XIN
    w(R, P("xk"), P("sum"), s1="input", s2="input")
    w(G, P("kvec"), P("xk"), s2="input")
    w(R, P("xk"), P("dx"), s1="output", s2="input")
    w(G, P("fk"), P("dx"), s2="input")
    w(R, P("sum"), P("sq"), s1="input", s2="input")
    # A = {sum, sq} -> mean, esq
    w(R, P("sum"), P("sq"), s1="output", s2="output")
    w(R, P("sq"), P("mean"), s1="output", s2="input")
    w(R, P("mean"), P("esq"), s1="input", s2="input")
    # F: red to m2, green to dx
    w(R, P("mean"), P("m2"), s1="output", s2="input")
    w(G, P("mean"), P("dx"), s1="output", s2="input")
    # C (green) = {esq out, m2 out, var in}
    w(G, P("esq"), P("m2"), s1="output", s2="output")
    w(G, P("m2"), P("var"), s1="output", s2="input")
    w(R, P("var"), P("vp"), s1="output", s2="input")
    # VNET (red): vp out, veps, all a_i inputs, all s0 inputs
    w(R, P("vp"), P("veps"), s1="output")
    w(R, P("vp"), P(f"a{n_iter}"), s1="output", s2="input")
    for i in range(n_iter, 1, -1):
        w(R, P(f"a{i}"), P(f"a{i - 1}"), s1="input", s2="input")
    w(R, P("a1"), P("s0_1"), s1="input", s2="input")
    for k in range(2, k_max + 1):
        prev = P(f"s0_{k - 1}") if k != 9 else P("s0_1")
        w(R, prev, P(f"s0_{k}"), s1="input", s2="input")
        w(G, prev, P(f"s0_{k}"), s1="output", s2="output")     # S0 (green)
    w(G, P("s0_8"), P("sone"), s1="output")
    # S0 -> a1/b1 (green); T_i (red) a_i -> b_i; S_i (green) b_i -> a_{i+1}, b_{i+1}
    w(G, P("s0_1"), P("a1"), s1="output", s2="input")
    for i in range(1, n_iter + 1):
        w(G, P(f"a{i}"), P(f"b{i}"), s1="input", s2="input")
        w(R, P(f"a{i}"), P(f"b{i}"), s1="output", s2="input")
        if i < n_iter:
            w(G, P(f"b{i}"), P(f"a{i + 1}"), s1="output", s2="input")
    w(G, P(f"b{n_iter}"), P("norm"), s1="output", s2="input")    # S final
    # back chain
    w(R, P("dx"), P("x1000"), s1="output", s2="input")    # dx = (x + K) - (mean + K)
    w(R, P("x1000"), P("norm"), s1="output", s2="input")
    w(R, P("norm"), P("gam"), s1="output", s2="input")
    w(G, P("gamma"), P("gam"), s2="input")
    w(R, P("gam"), P("out"), s1="output", s2="input")
    w(R, P("out"), P("beta"), s1="output")
    if power:
        b.pole(P("sub"), ox + 8, oy + 5, name="substation", size=2, quality="legendary")
    return dict(xin=P("xk"), out=P("out"))
