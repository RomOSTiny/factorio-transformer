"""Offline gate for the WHOLE final model running autonomously (final_gen): build with a prompt, RST, RUN,
let the clock run; every position's argmax is compared with final_ref's greedy decoding, and the settle
time of every position is measured (the tick of the last change of NEXT after the position starts).

  python sim_final_run.py "<prompt>" [n_positions] [Tp] [Tc]
Writes final_blueprint.txt / final_ids.json / final_info.json (the live build uses them).
"""
import json
import sys
import time

import numpy as np

import final_ref as F
from circuit_sim import GREEN_IN, RED_IN, Sim
from final_blocks import CHARS
from final_gen import NEXT_SIG, build_final

sys.stdout.reconfigure(encoding="utf-8")
prompt = sys.argv[1].replace("\\n", "\n") if len(sys.argv) > 1 else "you: hi!\nbot: "
N_POS = int(sys.argv[2]) if len(sys.argv) > 2 else len(prompt) + 8
Tp = int(sys.argv[3]) if len(sys.argv) > 3 else 600
Tc = int(sys.argv[4]) if len(sys.argv) > 4 else 540

t0 = time.time()
M = F.IntModel()
ptoks = [CHARS.index(c) for c in prompt]
toks = list(ptoks)
while len(toks) < N_POS + 1:
    toks.append(int(np.argmax(M.forward(toks)[-1])))
ref = M.forward(toks)
expect = [int(np.argmax(ref[i])) for i in range(N_POS)]
print(f"prompt {prompt!r}; reference continuation {''.join(CHARS[t] for t in toks[len(ptoks):])!r}", flush=True)

b, info = build_final(prompt, Tp=Tp, Tc=Tc, M=M)
bp, idmap = b.result()
open("final_blueprint.txt", "w").write(bp)
json.dump(idmap, open("final_ids.json", "w"))
json.dump(info, open("final_info.json", "w"))
print(f"built {len(idmap)} entities in {time.time() - t0:.0f}s", flush=True)
sim = Sim(bp)
num = {e["id"]: k + 1 for k, e in enumerate(idmap)}
S = info["signals"]
print(f"sim ready {time.time() - t0:.0f}s", flush=True)


def clock():
    return sim.out[num[info["clock"]]].get(S["clk"], 0)


def nxt():
    return sim.net(num["next_sink"], RED_IN).get(NEXT_SIG, 0)


sim.set_const(num[info["cmd"]], {S["rst"]: 1})
sim.step(20)
sim.set_const(num[info["cmd"]], {S["run"]: 1})
bad = worst = 0
for i in range(N_POS):
    start = i * Tp
    last_change, prev = None, nxt()
    for _ in range(Tp * 3):
        c = clock()
        if c >= start + Tc - 1:
            break
        sim.step()
        v = nxt()
        if v != prev and c >= start:
            last_change, prev = c - start, v
    got = nxt()
    ok = got == expect[i]
    bad += not ok
    worst = max(worst, last_change or 0)
    print(f"pos {i:3d} next {CHARS[got]!r} ref {CHARS[expect[i]]!r} {'OK ' if ok else 'BAD'} settled at +{last_change} "
          f"({time.time() - t0:.0f}s)", flush=True)
for _ in range(Tp):
    sim.step()
cells = []
for j in range(N_POS + 1):
    cid = f"ctl_cell_{j}" if j < len(ptoks) else f"ctl_hold_{j}"
    net = sim.net(num[cid], GREEN_IN)
    cells.append(info["vocab"].index(next(iter(net))) if len(net) == 1 else -1)
text = "".join(CHARS[c] for c in cells if c >= 0)
print(f"token buffer: {text!r}; == reference: {cells == toks[:N_POS + 1]}")
print(f"mismatches {bad}, worst settle +{worst} ticks (Tc {Tc}), overflow entities {len(sim.ovf)}, {time.time() - t0:.0f}s")
print("SIM FINAL RUN", "OK" if bad == 0 and cells == toks[:N_POS + 1] else "FAILED")
