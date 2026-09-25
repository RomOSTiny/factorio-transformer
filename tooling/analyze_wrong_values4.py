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

observed = {0: 0, 1: 0, 2: 0, 3: -460, 4: 690, 5: -7860, 6: 7050, 7: -3600, 8: 1610, 9: 4480, 10: -3350, 11: 5200}

print("--- hypothesis: drop exactly one term (k) from the 5 ---")
for j in range(3, 12):
    row = weight_rom_per_out[j]
    terms = [row[k] * x_values[k] for k in range(5)]
    full = sum(terms)
    matches = [k for k in range(5) if full - terms[k] == observed[j]]
    print(j, "drop-k matches:", matches, "full=", full, "target=", observed[j])

print()
print("--- hypothesis: double-count exactly one term (k) ---")
for j in range(3, 12):
    row = weight_rom_per_out[j]
    terms = [row[k] * x_values[k] for k in range(5)]
    full = sum(terms)
    matches = [k for k in range(5) if full + terms[k] == observed[j]]
    print(j, "double-k matches:", matches)

print()
print("--- hypothesis: only sum a SUBSET of terms (any subset of 0..4) ---")
from itertools import combinations
for j in range(3, 12):
    row = weight_rom_per_out[j]
    terms = [row[k] * x_values[k] for k in range(5)]
    found = []
    for r in range(0, 6):
        for combo in combinations(range(5), r):
            if sum(terms[k] for k in combo) == observed[j]:
                found.append(combo)
    print(j, "subset matches:", found)
