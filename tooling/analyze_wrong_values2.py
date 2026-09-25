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

acc_raw = [sum(weight_rom_per_out[j][k] * x_values[k] for k in range(5)) for j in range(N_OUT)]
observed = {0: 0, 1: 0, 2: 0, 3: -460, 4: 690, 5: -7860, 6: 7050, 7: -3600, 8: 1610, 9: 4480, 10: -3350, 11: 5200}
diffs = {j: observed[j] - acc_raw[j] for j in range(3, 12)}
print("diffs (observed-expected) for j=3..11:", diffs)

# search: is diff[j] explained by a MISSING or EXTRA single term weight_rom[a][k]*x_values[k2]?
print()
print("--- searching for single-term matches to each diff ---")
for j in range(3, 12):
    target = diffs[j]
    matches = []
    for a in range(N_OUT):
        for k in range(5):
            for k2 in range(5):
                v = weight_rom_per_out[a][k] * x_values[k2]
                if v == target or v == -target:
                    matches.append((a, k, k2, v))
    print(f"j={j} diff={target} matches={matches[:6]}")
