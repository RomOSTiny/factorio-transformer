"""Benchmark: how much does ONE combinator doing a WIDE vector operation cost per tick?

Layout: a shared input network of `width` signals (red), then `n` rows, each = a constant combinator
holding `width` weight signals (green) + an arithmetic `each(red) * each(green) -> out_i` (a full dot
product of `width` terms in ONE combinator). This is the alternative to one multiplier per weight:
the same MACs per tick, but ~2 entities per matrix ROW instead of one per weight.

  python bench_vector.py build X Y [n] [width]
  python bench_vector.py clear X Y [n] [width]
"""
import sys

from circuit_builder import EACH, G, R, Builder
from draftsman.data import signals as SD

MODE, TX, TY = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
N = int(sys.argv[4]) if len(sys.argv) > 4 else 2000
WIDTH = int(sys.argv[5]) if len(sys.argv) > 5 else 256
RESERVED = {"signal-everything", "signal-each", "signal-anything", "signal-P", "signal-S"}
POOL = [s for s in list(SD.virtual) + list(SD.item) + list(SD.fluid) if s not in RESERVED]
assert len(POOL) >= WIDTH, f"pool {len(POOL)} < width {WIDTH}"
SIGS = POOL[:WIDTH]
OUT = [s for s in POOL if s not in SIGS][:1] or ["signal-S"]


def build():
    b = Builder(f"bench vector n{N} w{WIDTH}")
    b.const("x_src", -3, 2, {s: 100 + i for i, s in enumerate(SIGS)})
    # a ticking signal on the input network: without a change every tick the game does not recompute
    # the dot combinators at all (idle entities cost ~35 ns, the vector work costs nothing)
    b.arith("tick", -3, 4, "signal-N", "+", 1, "signal-N")
    b.wire(R, "tick", "tick", s1="output", s2="input")
    b.wire(R, "tick", "x_src", s1="output")
    ROWS_PER_COL = 100
    prev_in = None
    for i in range(N):
        col, row = divmod(i, ROWS_PER_COL)
        x, y = col * 5, row * 2 + 2
        b.const(f"w_{i}", x, y, {s: (i + k) % 7 - 3 for k, s in enumerate(SIGS)})
        b.arith(f"dot_{i}", x + 1, y, EACH, "*", EACH, "signal-S", R, G)
        b.wire(G, f"w_{i}", f"dot_{i}", s2="input")
        if i == 0:
            b.wire(R, "x_src", f"dot_{i}", s2="input")
        elif row == 0:
            b.wire(R, f"dot_{i - ROWS_PER_COL}", f"dot_{i}", s1="input", s2="input")   # top of previous column
        else:
            b.wire(R, f"dot_{i - 1}", f"dot_{i}", s1="input", s2="input")
        prev_in = f"dot_{i}"
        if row == ROWS_PER_COL - 1 or i == N - 1:
            b.const(f"sink_{i}", x + 2, y, {})
            b.wire(R, f"dot_{i}", f"sink_{i}", s1="output")
    ncols = (N + ROWS_PER_COL - 1) // ROWS_PER_COL
    width_tiles = ncols * 5 + 4
    for col in range(ncols):
        for gy in range(0, ROWS_PER_COL * 2 + 4, 16):
            b.substation(f"sub_{col}_{gy}", col * 5 + 3, gy)
    b.connect_power()
    b.eei(width_tiles + 2, 0)
    assert not b.unpowered(), b.unpowered()[:5]
    return b.result()


if __name__ == "__main__":
    import json
    from block_live import LiveBlock
    bp_string, idmap = build()
    open("bench_vector_bp.txt", "w").write(bp_string)
    json.dump(idmap, open("bench_vector_ids.json", "w"))
    print(f"n={N} width={WIDTH}: {len(idmap)} entities, {N * WIDTH:,} MACs per tick")
    blk = LiveBlock("bench_vector_bp.txt", "bench_vector_ids.json", TX, TY, margin=20, timeout=600)
    if MODE == "clear":
        print(blk.clear())
    else:
        print(blk.recon())
        print(blk.lua('local s = game.surfaces["nauvis"]; local n = 0; '
                      f'for _, e in pairs(s.find_entities_filtered{{area={blk.area}, type={{"tree", "simple-entity", "cliff", "unit-spawner", "turret"}}}}) do '
                      'e.destroy(); n = n + 1 end; rcon.print("cleared " .. n)'))
        for line in blk.build():
            pass
        print("built; verify:", {k: v for k, v in blk.verify(chunk=3000).items() if k in ("entities", "missing_entities", "wires", "wires_missing", "ok", "status")})
    blk.close()
