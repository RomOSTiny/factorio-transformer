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

# flat weight list with (out_idx,in_idx) tag
weights = []
for j in range(N_OUT):
    for k in range(5):
        weights.append((j, k, weight_rom_per_out[j][k]))

extras = {1: -1120, 2: 3360, 3: -1120, 4: -3360, 6: 2240, 7: -2240, 9: -3360, 10: 1120}

print("--- any W (from ANY out_idx/in_idx) times any X gives this value? (mismatched pairing) ---")
for gate, val in extras.items():
    matches = []
    for (j, k, w) in weights:
        for xi, x in enumerate(x_values):
            if w * x == val:
                matches.append((j, k, w, xi, x))
    print(f"gate {gate} extra={val}: {matches[:8]}{' ...' if len(matches)>8 else ''}")

print()
print("--- is it a SUM of two terms from the gate's own 5? ---")
for gate, val in extras.items():
    row = weight_rom_per_out[gate]
    terms = [row[k] * x_values[k] for k in range(5)]
    found = []
    for a in range(5):
        for b in range(a + 1, 5):
            if terms[a] + terms[b] == val:
                found.append((a, b))
    print(f"gate {gate} extra={val}: pair-sum matches {found}, own terms={terms}")
