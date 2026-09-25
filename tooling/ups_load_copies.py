"""Load test for the world ceiling: build extra copies of the whole model (model_blueprint.txt) side by side.

  python ups_load_copies.py build K0 K1     copies k = K0..K1-1 at x = 17500 + 350*(k+1), y = 3000
  python ups_load_copies.py run   K0 K1     RST + RUN on those copies (they generate text)
  python ups_load_copies.py clear K0 K1     destroy them again
"""
import json
import subprocess
import sys
import time

MODE, K0, K1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
PY = sys.executable


def at(k):
    return 17500 + 350 * (k + 1), 3000


for k in range(K0, K1):
    x, y = at(k)
    t0 = time.time()
    if MODE == "build":
        for step in ("recon", "prep", "build"):
            out = subprocess.run([PY, "model_live.py", step, str(x), str(y)], capture_output=True, text=True).stdout
            lines = [l for l in out.splitlines() if l.strip() and "add_section" not in l]
            print(f"copy {k} ({x},{y}) {step}: {lines[-1] if lines else ''}", flush=True)
    elif MODE == "clear":
        out = subprocess.run([PY, "model_live.py", "clear", str(x), str(y)], capture_output=True, text=True).stdout
        print(f"copy {k}: {out.strip()}", flush=True)
    elif MODE == "run":
        sys.argv = sys.argv[:1]
        from block_live import LiveBlock
        info = json.load(open("model_info.json"))
        S = info["signals"]
        blk = LiveBlock("model_blueprint.txt", "model_ids.json", x, y, margin=20, timeout=300)
        blk.set_consts({info["cmd"]: {S["rst"]: 1}})
        time.sleep(0.2)
        blk.set_consts({info["cmd"]: {S["run"]: 1}})
        blk.close()
        print(f"copy {k} running", flush=True)
    print(f"  {time.time() - t0:.0f}s", flush=True)
