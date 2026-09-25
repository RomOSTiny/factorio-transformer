import json

with open("stage2_smoke_weights.json") as f:
    ref = json.load(f)

SCALE = 100
DIM = ref["dim"]
N_IN = DIM
N_OUT = 3 * DIM
H1_POS0 = [-1.27, -0.3464, 1.501, 0.1155]
Wqkv = ref["Wqkv"]
bqkv = ref["bqkv"]


def q(x):
    return int(round(x * SCALE))


x_values = [q(v) for v in H1_POS0] + [SCALE]
weight_rom_per_out = []
for oi in range(N_OUT):
    row = [q(Wqkv[ii][oi]) for ii in range(N_IN)] + [q(bqkv[oi])]
    weight_rom_per_out.append(row)

expected_terms = {}
for j in range(N_OUT):
    expected_terms[j] = [weight_rom_per_out[j][k] * x_values[k] for k in range(5)]

log = json.load(open(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\gate_fire_log.json", encoding="utf-8"))["log"]

by_gate = {}
for entry in log:
    by_gate.setdefault(entry["gate"], []).append((entry["tick"], entry["p"]))

for j in sorted(by_gate):
    firings = by_gate[j]
    exp = expected_terms[j]
    print(f"gate {j}: {len(firings)} firings (expected 5), expected_terms={exp}")
    for tick, p in firings:
        match = [k for k in range(5) if exp[k] == p]
        print(f"   tick={tick} p={p}  matches_term_k={match}")
    picked_sum = sum(p for _, p in firings)
    print(f"   sum of firings={picked_sum}, full expected sum={sum(exp)}")
    print()
