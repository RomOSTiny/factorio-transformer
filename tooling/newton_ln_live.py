"""Live runner for stage2_newton_ln_test.py: python newton_ln_live.py recon|build|verify|run|clear X Y"""
import json
import sys
import time

from block_live import LiveBlock

MODE, TX, TY = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
blk = LiveBlock("newton_ln_test_blueprint.txt", "newton_ln_test_ids.json", TX, TY)
if MODE == "recon":
    print(blk.recon())
elif MODE == "clear":
    print(blk.clear())
elif MODE == "build":
    for line in blk.build():
        print(line)
elif MODE == "verify":
    print(json.dumps(blk.verify(), indent=1))
elif MODE == "run":
    X = json.load(open("newton_ln_test_expect.json"))
    dims, blocks = X["dims"], X["blocks"]
    vec = lambda v: {dims[d]: int(a) for d, a in enumerate(v) if a}
    bad = 0
    for i in range(len(blocks["A"])):
        blk.set_consts({f"{n}_x_src": vec(blocks[n][i]["x"]) for n in blocks})
        time.sleep(0.4)
        got = blk.read({n: (f"{n}_sink", "circuit_red") for n in blocks})
        line = []
        for n in blocks:
            want = vec(blocks[n][i]["out"])
            ok = got[n] == want
            bad += not ok
            line.append(f"{n}:{'OK ' if ok else 'BAD'}")
            if not ok:
                d = {k: (got[n].get(k), want.get(k)) for k in set(got[n]) | set(want) if got[n].get(k) != want.get(k)}
                line.append(f"diff(live,ref)={dict(list(d.items())[:5])}")
        print(f"pos {i:2d}", " ".join(line))
    print(f"mismatches {bad} of {2 * len(blocks['A'])}")
    print("LIVE NEWTON LN", "OK" if bad == 0 else "FAILED")
blk.close()
