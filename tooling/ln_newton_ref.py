"""Circuit-exact reference for the Newton LayerNorm (P3.5): rsqrt ROM replaced by integer Newton sqrt.

One combinator (or a small bank) per line, exactly as newton_ln_lib builds it:
  E = sum x, G = sum x*x                       each+0 -> E, each*each -> G
  mean = E / DIM, esq = G / DIM                truncation toward zero
  var = esq - mean*mean  (>= 0 always: esq > mean^2 - 1 for integers)
  v = var * LN_P + EPS_P  (>= EPS_P >= 1)       v ~ (sqrt(LN_P) * SCALE * sigma)^2
  s0 = 1 + sum_k [v >= 4^k] * 2^(k-1) = 2^floor(log4 v)   decider bank, k = 1..K_MAX
  N_ITER times: t = v / s ; s = t/2 + s/2      two combinators (each/2 -> S sums the halves)
  dx = x - mean ; n = dx * SCALE * sqrt(LN_P) / s ; out = n * gq / SCALE + bq
Needs v >= 2 to keep s > 0 (checked: 4 iterations give |s - isqrt(v)| <= 1 for 10 <= v < 4^15).
"""
import math

import numpy as np


def make_ln_consts(scale=100, dim=32, ln_p=100, n_iter=4, k_max=15, eps=1e-5):
    rt = math.isqrt(ln_p)
    assert rt * rt == ln_p
    return dict(scale=scale, dim=dim, ln_p=ln_p, rt=rt, n_iter=n_iter, k_max=k_max,
                eps_p=max(1, round(eps * scale * scale * ln_p)))


def fdiv(a, b):
    """Factorio integer division: truncation toward zero, x/0 = 0."""
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def tdiv(a, b):
    a = np.asarray(a, dtype=np.int64)
    return np.where(a >= 0, a // b, -((-a) // b))


def newton_sqrt(v, C):
    s = 1 + sum(2 ** (k - 1) for k in range(1, C["k_max"] + 1) if v >= 4 ** k)
    for _ in range(C["n_iter"]):
        t = fdiv(v, s)
        s = fdiv(t, 2) + fdiv(s, 2)
    return s


def layernorm_row(r, gq, bq, C, trace=None):
    r = np.asarray(r, dtype=np.int64)
    dim, scale = C["dim"], C["scale"]
    E, Gs = int(r.sum()), int((r * r).sum())
    mean, esq = fdiv(E, dim), fdiv(Gs, dim)
    var = esq - mean * mean
    v = var * C["ln_p"] + C["eps_p"]
    s = newton_sqrt(v, C)
    dx = r - mean
    n = np.array([fdiv(int(d) * scale * C["rt"], s) for d in dx], dtype=np.int64)
    out = tdiv(n * np.asarray(gq, dtype=np.int64), scale) + np.asarray(bq, dtype=np.int64)
    if trace is not None:
        trace.update(E=E, G=Gs, mean=mean, esq=esq, var=var, v=v, s=s, n=n.tolist())
    return out


def layernorm(x, gq, bq, C):
    return np.stack([layernorm_row(r, gq, bq, C) for r in np.asarray(x, dtype=np.int64)])
