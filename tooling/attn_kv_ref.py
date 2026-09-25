"""Circuit-exact reference for ONE attention step with a KV cache (dense attention, P3).

The circuit processes one position i at a time: k_i/v_i are written into cache
cell i, then q_i attends over cells 0..i. Every stage below is one vector
combinator (or a small bank of them) in dense_attn_lib, and the integer
semantics here are exactly what those combinators compute:

  raw'_j = q_hd . k_j,hd + OFF      score combinator: each(red q_hd) * each(green k cell)
                                    -> K_j; the k cell also holds signal V=OFF and the
                                    q_hd network a constant V=1, so the dot gets +OFF
                                    (unwritten cells stay empty -> key absent = masked)
  sc'_j  = raw'_j / DIVQ            positive, so Factorio truncation == floor
  M      = max_j sc'_j              selector combinator (select max, index 0)
  u_j    = (M + 1) - sc'_j >= 1     never 0, so no key is dropped by the network
  e_j    = sum_t [u_j <= W*t]*d_t   bank of deciders "each <= W*t -> each = d_t";
                                    telescopes to EXP_T[(u_j - 1) // W]
  S      = sum_j e_j
  w_j    = e_j * SCALE / S
  att_hd = (sum_j w_j * v_j)|hd / SCALE   (truncation toward zero, like Factorio)

Only difference from the first stage2_real_ref: the score division is floor, not
truncation toward zero (the OFF shift makes the divided value positive).
"""
import math

import numpy as np

OFFC = 100000           # OFF = OFFC * DIVQ keeps raw' > 0 (|q.k| <= 1.7e6 on real data)


def make_consts(scale=100, n_buckets=200, head_dim=8, x_min=16.0):
    divq = round(scale * math.sqrt(head_dim))
    width = max(1, round(scale * x_min / n_buckets))
    exp_t = [int(round(scale * math.exp(-(i + 0.5) * width / scale))) for i in range(n_buckets)]
    padded = exp_t + [0]
    steps = [(t, padded[t - 1] - padded[t]) for t in range(1, n_buckets + 1) if padded[t - 1] != padded[t]]
    return dict(scale=scale, divq=divq, off=OFFC * divq, width=width, exp_t=exp_t,
                steps=steps, thresholds=[(width * t, d) for t, d in steps])


def tdiv(a, b):
    a = np.asarray(a, dtype=np.int64)
    return np.where(a >= 0, a // b, -((-a) // b))


def exp_steps(u, C):
    """Decider bank: e = sum over thresholds of (u <= thr) * delta."""
    u = np.asarray(u, dtype=np.int64)
    e = np.zeros_like(u)
    for thr, d in C["thresholds"]:
        e += (u <= thr) * d
    return e


def attn_step(q_i, K, V, heads, C, trace=None):
    """q_i: (DIM,), K, V: (n, DIM) = cache cells 0..i. Returns att (DIM,) int64.

    If trace is a dict, per-head intermediates are stored in it (for live checks).
    """
    q_i = np.asarray(q_i, dtype=np.int64)
    K = np.asarray(K, dtype=np.int64)
    V = np.asarray(V, dtype=np.int64)
    dim = q_i.shape[0]
    hd_n = dim // heads
    scale = C["scale"]
    att = np.zeros(dim, dtype=np.int64)
    for hd in range(heads):
        sl = slice(hd * hd_n, (hd + 1) * hd_n)
        raw = K[:, sl] @ q_i[sl] + C["off"]
        assert (raw > 0).all() and (raw < 2 ** 31).all()
        sc = raw // C["divq"]
        M = int(sc.max())
        u = (M + 1) - sc
        e = exp_steps(u, C)
        # the closed form the decider bank must reproduce
        assert (e == np.array([C["exp_t"][j] if j < len(C["exp_t"]) else 0 for j in (u - 1) // C["width"]])).all()
        S = int(e.sum())
        w = (e * scale) // S
        acc = w @ V                      # all DIM dims; the circuit filters to head dims after the sum
        att[sl] = tdiv(acc[sl], scale)
        if trace is not None:
            trace[hd] = dict(raw=raw.tolist(), sc=sc.tolist(), M=M, u=u.tolist(), e=e.tolist(), S=S,
                             w=w.tolist(), acc=acc.tolist(), att=att[sl].tolist())
    return att


def attention_seq(Q, K, V, heads, C):
    """Causal attention over a whole sequence, one KV-cache step per position."""
    return np.stack([attn_step(Q[i], K[:i + 1], V[:i + 1], heads, C) for i in range(Q.shape[0])])
