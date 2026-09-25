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

extras = {1: -1120, 2: 3360, 3: -1120, 4: -3360, 6: 2240, 7: -2240, 9: -3360, 10: 1120}

all_terms = {}
for j in range(N_OUT):
    for k in range(5):
        all_terms.setdefault(weight_rom_per_out[j][k] * x_values[k], []).append((j, k))

for gate, val in extras.items():
    print(f"gate {gate} extra={val} -> matches (out_idx,in_idx): {all_terms.get(val, 'NONE')}")
