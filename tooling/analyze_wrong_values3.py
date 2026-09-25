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
print("diffs:", diffs)
print()

# Full weight_rom is a FLAT array of length N_OUT*5=60, addressed 0..59 as
# weight_rom_flat[out_idx*5+in_idx]. Reconsider: what if the observed value
# corresponds to summing weight_rom_flat[k]*x_values[k % 5] over some WRONG
# range of k (e.g. shifted start/end), instead of exactly [j*5, j*5+4]?
flat = []
for oi in range(N_OUT):
    flat.extend(weight_rom_per_out[oi])
print("flat len:", len(flat))


def window_sum(start):
    return sum(flat[start + k] * x_values[k] for k in range(5)) if 0 <= start and start + 4 < len(flat) else None


print()
print("--- does observed[j] match window_sum(start) for some OTHER start (address offset)? ---")
for j in range(3, 12):
    target = observed[j]
    found = []
    for start in range(0, len(flat) - 4):
        if window_sum(start) == target:
            found.append(start)
    print(f"j={j} (own start={j*5}) target={target} matching starts={found}")
