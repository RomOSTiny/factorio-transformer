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

# expected (correct) raw acc per out_idx
expected = []
for oi in range(N_OUT):
    s = sum(q(Wqkv[i][oi]) * x_values[i] for i in range(N_IN)) + q(Wqkv[N_IN - 1][oi]) * 0  # placeholder
    expected.append(None)

expected = []
for oi in range(N_OUT):
    terms = [q(Wqkv[ii][oi]) * x_values[ii] for ii in range(N_IN)]
    terms.append(q(bqkv[oi]) * x_values[N_IN])  # bias * SCALE(=100, representing "1")
    expected.append(sum(t // SCALE for t in terms))  # each term is W*X, both already xSCALE, so /SCALE once matches export's q() usage... let's just check raw sums directly instead

# Actually just replicate EXACT export logic: weight_rom holds q(W) and q(bias) at N_IN'th slot,
# x_values holds q(x) and SCALE at N_IN'th slot (bias input = "1" represented as SCALE).
# acc_raw = sum over in_idx=0..N_IN of weight_rom[in_idx]*x_values[in_idx]  (this is the RAW, pre /100 accumulator)
acc_raw = []
weight_rom_per_out = []
for oi in range(N_OUT):
    row = [q(Wqkv[ii][oi]) for ii in range(N_IN)] + [q(bqkv[oi])]
    weight_rom_per_out.append(row)
    total = sum(row[k] * x_values[k] for k in range(N_IN + 1))
    acc_raw.append(total)

print("expected acc_raw (should match out*100):")
print(acc_raw)
print("expected out (acc/100):", [round(v / 100) for v in acc_raw])

observed = {0: 0, 1: 0, 2: 0, 3: -460, 4: 690, 5: -7860, 6: 7050, 7: -3600, 8: 1610, 9: 4480, 10: -3350, 11: 5200}

print()
print("comparing observed vs expected acc_raw:")
for j in range(12):
    print(j, "observed=", observed[j], "expected=", acc_raw[j], "diff=", observed[j] - acc_raw[j])

# Hypothesis: observed[j] corresponds to expected[j] computed with SHIFTED in_idx alignment
# (weight_rom[in_idx] * x_values[in_idx+shift] or similar). Try a few shift/window hypotheses.
print()
print("--- hypothesis scan: sum of weight_rom[j][k]*x_values[k2] over various k/k2 offset combos ---")
for shift in range(-2, 3):
    vals = []
    for j in range(12):
        row = weight_rom_per_out[j]
        total = 0
        for k in range(5):
            k2 = k + shift
            if 0 <= k2 < 5:
                total += row[k] * x_values[k2]
        vals.append(total)
    print("shift", shift, vals)
