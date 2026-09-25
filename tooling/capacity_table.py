"""World-ceiling table from the 21.09.2026 load test (Reshenie 48): model config -> combinators, UPS, RAM, time/token.

Measured (Ryzen 5 5600, 16 GB): computing combinators N vs max UPS (game.speed unlocked), models generating:
  74K 2.06 ms | 242K 8.52 ms | 578K 22.1 ms | 1418K 50.0 ms per tick  (~35 ns/combinator, linear)
  Factorio RAM ~0.6 GB + ~1.57 KB per computing combinator (entities incl. poles/constants).
Tick depth per token: ~55 ticks per layer + ~25 (sim of the rehearsal: 164-180 ticks for 3 layers).
"""
NS_PER_COMB = 37e-6          # ms per combinator per tick (35 measured + margin)
BASE_MS = 0.5


def combinators(d, L, c, V=35, f=None, h=None):
    f = f or 4 * d
    h = h or max(4, d // 32)
    per_layer = 4 * d * d + 2 * d * f + (5 * d + f) + 4 * c + 2 * h * c + 46 * h + 80
    return L * per_layer + d * V + V + 2 * c + 4 * c + 300


def params(d, L, c, V=35, f=None):
    f = f or 4 * d
    return L * (4 * d * d + 2 * d * f + 4 * d + f + 4 * d) + (V + c) * d + 2 * d


def row(d, L, c):
    n = combinators(d, L, c)
    ms = BASE_MS + NS_PER_COMB * n
    ups = 1000 / ms
    tp = round(1.25 * (55 * L + 25)) + 20
    return n, params(d, L, c), ups, tp, tp / ups, 0.6 + 1.57e-6 * n


if __name__ == "__main__":
    n, p, ups, tp, spt, ram = row(32, 3, 48)
    print(f"check rehearsal d32 L3 c48: formula {n:,} combinators (real 42,024), {p:,} params (real 40,832)")
    print(f"{'config':22s} {'params':>9s} {'combinators':>12s} {'UPS':>6s} {'ticks/tok':>9s} {'s/token':>8s} {'RAM GB':>7s} {'128 tok':>8s}")
    for d, L, c in [(64, 4, 128), (96, 6, 128), (128, 4, 128), (128, 8, 128), (128, 12, 128), (192, 6, 128),
                    (192, 8, 128), (256, 4, 128), (256, 6, 128), (256, 8, 128), (320, 8, 128)]:
        n, p, ups, tp, spt, ram = row(d, L, c)
        print(f"d={d:<3d} L={L:<2d} ctx={c:<4d}      {p / 1e6:7.2f}M {n / 1e6:10.2f}M {ups:6.1f} {tp:9d} {spt:8.0f} {ram:7.1f} {128 * spt / 60:6.0f}m")
