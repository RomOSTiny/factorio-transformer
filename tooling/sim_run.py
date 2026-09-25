"""Offline gate for the AUTONOMOUS model: build with a prompt, press RST then RUN, let the clock run.

  python sim_run.py tf  [start]          prompt = the whole 48-char window: every position's argmax is
                                          checked against stage2_real_ref (teacher forcing)
  python sim_run.py gen [start] [plen]   prompt = first plen chars; the model writes the rest itself;
                                          checked against the reference's greedy decoding
Writes model_blueprint.txt / model_ids.json / model_info.json for the live build.
"""
import json
import sys
import time

import numpy as np

MODE = sys.argv[1] if len(sys.argv) > 1 else "gen"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
PLEN = int(sys.argv[3]) if len(sys.argv) > 3 else 12
sys.argv = sys.argv[:1]
import stage2_real_ref as R
from circuit_sim import GREEN_IN, RED_IN, RED_OUT, Sim
from model_gen import NEXT_SIG, build_model
from stage2_tokenizer import decode

CTX = 48
window = [int(t) for t in np.load("stage2_data.npy")[START:START + CTX]]
prompt_toks = window if MODE == "tf" else window[:PLEN]
toks = list(prompt_toks)
while len(toks) < CTX:                                      # reference greedy continuation
    toks.append(int(np.argmax(R.forward(toks)[len(toks) - 1])))
ref = R.forward(toks)
expect_next = [int(np.argmax(ref[i])) for i in range(CTX)]
prompt = decode(prompt_toks)
print(f"mode {MODE}, prompt {prompt!r}")
if MODE == "gen":
    print(f"reference continuation: {decode(toks[len(prompt_toks):])!r}")

t0 = time.time()
b, info = build_model(prompt, ctx=CTX)
bp_string, idmap = b.result()
open("model_blueprint.txt", "w").write(bp_string)
json.dump(idmap, open("model_ids.json", "w"))
json.dump(info, open("model_info.json", "w"))
sim = Sim(bp_string)
num = {e["id"]: sim.by_pos[(e["x"], e["y"])] for e in idmap}
S = info["signals"]
Tp, Tc = info["Tp"], info["Tc"]
print(f"built {len(idmap)} entities in {time.time() - t0:.0f}s")


def clock():
    return sim.out[num[info["clock"]]].get(S["clk"], 0)


sim.set_const(num[info["cmd"]], {S["rst"]: 1})
sim.step(20)
sim.set_const(num[info["cmd"]], {S["run"]: 1})
bad = 0
for i in range(CTX - 1):
    target = i * Tp + Tc + 20
    for _ in range(Tp * 2):
        if clock() >= target:
            break
        sim.step()
    nxt = sim.net(num["next_sink"], RED_IN).get(NEXT_SIG, 0)
    ok = nxt == expect_next[i]
    bad += not ok
    if not ok or i % 8 == 0:
        print(f"pos {i:2d} clock {clock()} next {nxt:2d} ref {expect_next[i]:2d} {'OK' if ok else 'BAD'}", flush=True)
for _ in range(Tp * 2):
    sim.step()
if MODE == "gen":
    cells = []
    for j in range(CTX):
        cid = f"ctl_cell_{j}" if j < len(prompt_toks) else f"ctl_hold_{j}"
        net = sim.net(num[cid], GREEN_IN)          # prompt constants and hold inputs: green cell network
        cells.append(info["vocab"].index(next(iter(net))) if len(net) == 1 else -1)
    text = decode([c for c in cells if c >= 0])
    print(f"token buffer: {text!r}")
    ok_text = cells == toks
    print("buffer == reference greedy decode:", ok_text)
    bad += not ok_text
print(f"mismatches {bad}, sim {time.time() - t0:.0f}s")
print("SIM RUN", "OK" if bad == 0 else "FAILED")
