"""Offline gate for the final model's blocks: each block alone in a blueprint, driven by a constant with
the real input of a real position (final_ref trace), simulated (circuit_sim), compared with the trace.

  python final_block_test.py [layer] [pos...]     default: layer 0, positions 0 5 17
"""
import sys
import time

import numpy as np

import final_ref as F
from circuit_builder import R, Builder
from circuit_sim import Sim
from final_blocks import DELIVERY_CODE, VOCAB_SIGS, data_signals, place_final_ln, place_vec_matmul

sys.path.insert(0, DELIVERY_CODE)

PROMPT = "you: hi! what is your name?\nbot: "


def run_block(label, place, x_sigs, x_vals, out_sigs_groups):
    """place(B) -> ports; drives ports['xin'] with x, returns [dict per output group] after settle."""
    B = Builder(label)
    ports = place(B)
    B.const("x_src", -6, -8, {})
    (a, sa) = min(ports["xin"], key=lambda p: np.hypot(*np.subtract(B.pos[p[0]], B.pos["x_src"])))
    B.link(R, "x_src", None, a, sa, "xin")
    sinks = []
    for gi, grp in enumerate(ports["outs"]):
        sid = f"sink_{gi}"
        B.const(sid, -6, -10 - 2 * gi, {})
        B.link(R, grp[0][0], grp[0][1], sid, None, sid)
        sinks.append(sid)
    B.eei(-10, -8)
    B.connect_power()
    unp = B.unpowered()
    bp, idmap = B.result()
    num = {e["id"]: k + 1 for k, e in enumerate(idmap)}
    s = Sim(bp)
    s.set_const(num["x_src"], {k: int(v) for k, v in zip(x_sigs, x_vals) if int(v)})
    t = s.settle(2000)
    outs = [s.net(num[sid], 1) for sid in sinks]
    return outs, dict(entities=len(idmap), settle=t, unpowered=len(unp), ovf=len(s.ovf))


def compare(name, got, sigs, exp):
    g = np.array([got.get(k, 0) for k in sigs])
    bad = int((g != exp).sum())
    extra = set(got) - set(sigs)
    print(f"  {name}: {'OK' if not bad and not extra else 'MISMATCH'} ({bad} of {len(sigs)} differ, "
          f"extra signals {len(extra)}) max|diff| {int(np.abs(g - exp).max())}")
    return not bad and not extra


def main():
    layer = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    positions = [int(a) for a in sys.argv[2:]] or [0, 5, 17]
    M = F.IntModel()
    from tokenizer import encode_normalized
    tr = {}
    M.forward(encode_normalized(PROMPT).astype(np.int64), trace=tr)
    D, FF = M.dim, M.ffn
    dims, keys, ffs = data_signals(D, M.ctx, FF)
    Lw = M.L[layer]
    p = f"L{layer}."
    x_in = tr["x0"] if layer == 0 else tr[f"L{layer - 1}.x3"]

    ok = True
    for pos in positions:
        print(f"layer {layer} position {pos}:")
        t0 = time.time()
        g1, g2 = Lw["ln1"]
        outs, info = run_block("ln1", lambda B: place_final_ln(B, "ln1_", 0, 0, g1, g2, dims, F.LN_EPS_Q), dims,
                               x_in[pos], None)
        ok &= compare("ln1", outs[0], dims, tr[p + "h1"][pos])
        print("   ", info, f"{time.time() - t0:.1f}s")
        t0 = time.time()
        W, bias = Lw["qkv"]
        qkv_sigs = dims * 3
        outs, info = run_block("qkv", lambda B: place_vec_matmul(B, "qkv_", 0, 0, W.T.tolist(), (bias * 100).tolist(), dims,
                                                                 qkv_sigs, groups=[(D, R), (D, R), (D, R)]),
                               dims, tr[p + "h1"][pos], None)
        for gi, nm in enumerate("qkv"):
            ok &= compare(nm, outs[gi], dims, tr[p + "qkv"][pos][gi * D:(gi + 1) * D])
        print("   ", info, f"{time.time() - t0:.1f}s")
        t0 = time.time()
        W, bias = Lw["fc1"]
        outs, info = run_block("fc1", lambda B: place_vec_matmul(B, "fc1_", 0, 0, W.T.tolist(), (bias * 100).tolist(), dims,
                                                                 ffs, relu=True), dims, tr[p + "h2"][pos], None)
        ok &= compare("fc1+relu", outs[0], ffs, tr[p + "f1"][pos])
        print("   ", info, f"{time.time() - t0:.1f}s")
        t0 = time.time()
        W, bias = Lw["fc2"]
        outs, info = run_block("fc2", lambda B: place_vec_matmul(B, "fc2_", 0, 0, W.T.tolist(), (bias * 100).tolist(), ffs,
                                                                 dims), ffs, tr[p + "f1"][pos], None)
        ok &= compare("fc2", outs[0], dims, tr[p + "f2"][pos])
        print("   ", info, f"{time.time() - t0:.1f}s")
    if layer == M.layers - 1:
        for pos in positions:
            g1, g2 = M.lnf
            outs, info = run_block("lnf", lambda B: place_final_ln(B, "lnf_", 0, 0, g1, g2, dims, F.LN_EPS_Q), dims,
                                   tr[p + "x3"][pos], None)
            ok &= compare(f"ln_f pos {pos}", outs[0], dims, tr["xf"][pos])
            vs = VOCAB_SIGS
            outs, info = run_block("logits", lambda B: place_vec_matmul(B, "lg_", 0, 0, M.emb_q.tolist(), None, dims, vs),
                                   dims, tr["xf"][pos], None)
            ok &= compare(f"logits pos {pos}", outs[0], vs, tr["logits"][pos])
    print("BLOCKS OK" if ok else "BLOCKS MISMATCH")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
