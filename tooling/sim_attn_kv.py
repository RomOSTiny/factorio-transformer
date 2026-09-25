"""Offline gate: simulate the dense attention blueprint over all positions and compare with attn_kv_ref."""
import json
import sys

from circuit_sim import GREEN_IN, RED_IN, RED_OUT, Sim

bp_file, ids_file, exp_file = (sys.argv[1:4] if len(sys.argv) > 3 else
                               ("attn_kv_test_blueprint.txt", "attn_kv_test_ids.json", "attn_kv_test_expect.json"))
ids = json.load(open(ids_file))
X = json.load(open(exp_file))
dims, keys = X["dims"], X["keys"]
sim = Sim(open(bp_file).read())
num = {e["id"]: sim.by_pos[(e["x"], e["y"])] for e in ids}


def vec(v):
    return {dims[d]: int(x) for d, x in enumerate(v) if x}


sim.settle()
bad = 0
max_settle = 0
for i, st in enumerate(X["steps"]):
    sim.set_const(num["q_src"], vec(st["q"]))
    sim.set_const(num["k_src"], vec(st["k"]))
    sim.set_const(num["v_src"], vec(st["v"]))
    sim.set_const(num["ctl_src"], {"signal-W": i + 1})
    sim.step(5)
    sim.set_const(num["ctl_src"], {})
    max_settle = max(max_settle, sim.settle())
    got = sim.net(num["att_out"], RED_OUT)
    exp = vec(st["att"])
    if got != exp:
        bad += 1
        print(f"pos {i}: MISMATCH")
        for h in range(4):
            p = f"p{h}_"
            M = sim.net(num[p + "u"], RED_IN).get("signal-M")
            S = sim.net(num[p + "wdiv"], RED_IN).get("signal-S")
            eh = st["heads"][str(h)]
            print(f"   head {h}: M+1 sim={M} ref={eh['M'] + 1}  S sim={S} ref={eh['S']}")
        diff = {k: (got.get(k), exp.get(k)) for k in set(got) | set(exp) if got.get(k) != exp.get(k)}
        print("   att diff (sim, ref):", dict(list(diff.items())[:8]))
        if bad >= 3:
            break
print(f"positions {len(X['steps'])}, mismatches {bad}, max settle ticks after write {max_settle}")
print("SIM ATTENTION", "OK" if bad == 0 else "FAILED")
