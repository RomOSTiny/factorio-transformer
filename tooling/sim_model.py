"""Offline gate for the whole model: circuit_sim over a real window, position by position.

Per position i: ctrl = {T: token_i, P: i, W: i+1} -> settle (KV cells transparent) -> ctrl W=0 -> settle
(cells hold). Checks logits (all vocab) and the argmax id against stage2_real_ref.forward.
Usage: python sim_model.py [n_positions] [start]
"""
import json
import sys
import time

import numpy as np

N = int(sys.argv[1]) if len(sys.argv) > 1 else 48
START = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
sys.argv = sys.argv[:1]
import stage2_real_ref as R
from circuit_sim import RED_IN, Sim
from model_gen import NEXT_SIG, POS_SIG, TOK_SIG

info = json.load(open("model_info.json"))
ids = json.load(open("model_ids.json"))
vocab = info["vocab"]
toks = np.load("stage2_data.npy")[START:START + N].astype(np.int64)
ref = R.forward(list(toks))
t0 = time.time()
sim = Sim(open("model_blueprint.txt").read())
num = {e["id"]: sim.by_pos[(e["x"], e["y"])] for e in ids}
print(f"sim loaded {len(sim.ents)} entities in {time.time() - t0:.0f}s")
sim.settle(5000)
bad = 0
settles = []
for i, tk in enumerate(toks):
    ctrl = {TOK_SIG: int(tk), POS_SIG: i}
    sim.set_const(num["ctrl_src"], {**ctrl, "signal-W": i + 1})
    s1 = sim.settle(20000)
    logits = sim.net(num["logits_sink"], RED_IN)
    nxt = sim.net(num["next_sink"], RED_IN).get(NEXT_SIG, 0)
    sim.set_const(num["ctrl_src"], ctrl)
    s2 = sim.settle(20000)
    nxt2 = sim.net(num["next_sink"], RED_IN).get(NEXT_SIG, 0)
    settles.append(s1)
    if sim.ovf:
        print(f"pos {i}: SETTLED OVERFLOW in {len(sim.ovf)} combinators, e.g. {list(sim.ovf.items())[:3]}")
    want = {vocab[k]: int(v) for k, v in enumerate(ref[i]) if v}
    ok = logits == want and nxt == int(np.argmax(ref[i])) and nxt2 == nxt
    bad += not ok
    msg = "" if ok else f" logits_ok={logits == want} next={nxt}/{nxt2} ref={int(np.argmax(ref[i]))}"
    print(f"pos {i:2d} tok {int(tk):2d} next {nxt:2d} settle {s1:4d}+{s2:3d} {'OK ' if ok else 'BAD'}{msg}", flush=True)
    if bad >= 3:
        break
print(f"positions {len(settles)}, mismatches {bad}, settle ticks max {max(settles)}, sim {time.time() - t0:.0f}s")
print("SIM MODEL", "OK" if bad == 0 else "FAILED")
