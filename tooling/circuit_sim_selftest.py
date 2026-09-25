"""Check circuit_sim against the live-verified primitives micro-test (stage2_attn_prims_test.py)."""
import json

from circuit_sim import GREEN_IN, RED_IN, RED_OUT, Sim

spec = json.load(open("attn_prims_ids.json"))
sim = Sim(open("attn_prims_blueprint.txt").read())
num = {e["id"]: sim.by_pos[(e["x"], e["y"])] for e in spec["ids"]}
sim.settle()
reads = {"a": ("a_ar", RED_OUT), "b": ("b_ar", RED_OUT), "c": ("c_d1", RED_OUT), "d_sel": ("d_m", RED_IN),
         "d": ("d_m", RED_OUT), "e": ("e_ar", RED_OUT), "f": ("f_ar", RED_OUT), "h": ("h_ar", RED_OUT)}
ok_all = True
for k, (eid, cid) in reads.items():
    got = sim.net(num[eid], cid)
    ok = got == spec["expect"][k]
    ok_all &= ok
    print(f"{k:6s} {'OK ' if ok else 'BAD'} {got}")

E, AB = {}, {"signal-A": 11, "signal-B": 22}
ctl, data = num["g_ctl"], num["g_data"]
seq = [({}, None, (E, E)), ({"signal-W": 1}, None, (AB, E)), ({}, None, (AB, E)), ({}, 99, (AB, E)),
       ({"signal-W": 2}, None, (AB, {"signal-A": 99, "signal-B": 22})), ({}, None, (AB, {"signal-A": 99, "signal-B": 22})),
       ({"signal-R": 1}, None, (E, E)), ({}, None, (E, E))]
for c, a, (e1, e2) in seq:
    sim.set_const(ctl, c)
    if a is not None:
        sim.set_const(data, {"signal-A": a, "signal-B": 22})
    sim.step(30)
    got = (sim.net(num["g_hold1"], GREEN_IN), sim.net(num["g_hold2"], GREEN_IN))
    ok = got == (e1, e2)
    ok_all &= ok
    print(f"g {'OK ' if ok else 'BAD'} ctl={c} {got}")
print("SIM SELFTEST", "OK" if ok_all else "FAILED")
