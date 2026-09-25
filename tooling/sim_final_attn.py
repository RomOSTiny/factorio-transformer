"""Offline gate: the final attention block (final_attn_lib) simulated position by position on the real q/k/v
of a layer (final_ref trace of a real prompt), compared with final_ref's attention output.

  python sim_final_attn.py [layer] [n_positions]
"""
import sys
import time

import numpy as np

import final_ref as F
from circuit_builder import Builder
from circuit_sim import RED_IN, RED_OUT, Sim
from final_attn_lib import place_final_attn
from final_blocks import DELIVERY_CODE, data_signals

sys.path.insert(0, DELIVERY_CODE)
PROMPT = "you: hi! what is your name?\nbot: i am the engineer from nauvis.\nyou: tell me a joke.\nbot: "


def main():
    layer = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    M = F.IntModel()
    from tokenizer import encode_normalized
    ids = encode_normalized(PROMPT).astype(np.int64)
    n_pos = int(sys.argv[2]) if len(sys.argv) > 2 else len(ids)
    tr = {}
    M.forward(ids, trace=tr)
    D = M.dim
    dims, keys, _ = data_signals(D, M.ctx, M.ffn)
    steps = M.exp_steps()
    B = Builder("final attn test")
    place_final_attn(B, "", 0, 0, dims, keys, steps, F.ATT_OFF, heads=M.heads, n_cells=M.ctx, test_ports=True)
    B.eei(30, 0)
    B.connect_power()
    unp = B.unpowered()
    bp, idmap = B.result()
    print(f"entities {len(idmap)}, unpowered {len(unp)}, exp steps {len(steps)}")
    num = {e["id"]: k + 1 for k, e in enumerate(idmap)}
    sim = Sim(bp)
    sim.settle()
    qkv = tr[f"L{layer}.qkv"]
    att = tr[f"L{layer}.att"]

    def vec(v):
        return {dims[d]: int(x) for d, x in enumerate(v) if x}

    bad, max_settle, t0 = 0, 0, time.time()
    for i in range(n_pos):
        sim.set_const(num["q_src"], vec(qkv[i, :D]))
        sim.set_const(num["k_src"], vec(qkv[i, D:2 * D]))
        sim.set_const(num["v_src"], vec(qkv[i, 2 * D:]))
        sim.set_const(num["ctl_src"], {"signal-W": i + 1})
        sim.step(5)
        sim.set_const(num["ctl_src"], {})
        max_settle = max(max_settle, sim.settle(3000))
        got = sim.net(num["att_out"], RED_OUT)
        exp = vec(att[i])
        if got != exp:
            bad += 1
            diff = {k: (got.get(k), exp.get(k)) for k in set(got) | set(exp) if got.get(k) != exp.get(k)}
            print(f"pos {i}: MISMATCH {len(diff)} dims, e.g. {dict(list(diff.items())[:4])}")
            if bad >= 3:
                break
    print(f"layer {layer}: positions {n_pos}, mismatches {bad}, max settle ticks after write {max_settle}, "
          f"sim {time.time() - t0:.0f}s, overflow entities {len(sim.ovf)}")
    print("SIM FINAL ATTENTION", "OK" if bad == 0 else "FAILED")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
