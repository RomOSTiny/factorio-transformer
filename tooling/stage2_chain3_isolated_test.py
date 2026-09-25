"""
Isolated test #2 for the Sequencer: does a TIME-SHIFTED ROM sweep compose
across a multi-stage pipeline?

stage2_chain_isolated_test.py (passed 08.09.2026) proved a single guarded
capture: block B can latch block A's settled live value if B's capture is
gated on B's own tick counter reaching a build-time offset past A's settle.

But the real forward pass is a DAG ~12 stages deep, and each stage is a
SWEEP (not a single capture) that reads the previous stage's output as an
operand at EVERY address. A per-stage guard "T >= OFFSET" would kill the
sweep's early addresses. The fix tested here: shift the whole sweep in
time - each block computes its address from (t_ctr - START_OFFSET), so its
"address 0" lands at real tick START_OFFSET, chosen at build time to be
past the upstream stage's settle+bridge time. The block still free-runs
once from revival; only its address arithmetic is offset. START_OFFSET_N
is built from START_OFFSET_{N-1} + (stage N-1's sweep duration) + margin -
so the real question is whether that composition holds across 3 stages of
DIFFERENT sizes and periods.

  A: acc_a = sum(0..N_A-1)                      = 10        no offset
  B: for e in 0..N_B-1: acc_b += acc_a + e      = 4*10+6    = 46   offset ~320
  C: for g in 0..N_C-1: acc_c += acc_b + g      = 3*46+3    = 141  offset ~640

acc_c == 141 (vs the partial-read alternatives 3*21+3=66 or 3*33+3=102 a
too-small offset would give) is itself the discriminating result - each
stage must have read the PREVIOUS stage's fully settled output.
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

RED, GREEN = "red", "green"
bp = Blueprint()
bp.label = "chain-3 time-shifted sweep composition test (Sequencer prerequisite)"

K_A, N_A = 50, 5
K_B, N_B = 60, 4
K_C, N_C = 70, 3
SETTLE_MARGIN = 60
BRIDGE_HOPS_EST = 5  # upper bound; SETTLE_MARGIN absorbs the slack

EXP_A = sum(range(N_A))                       # 10
EXP_B = N_B * EXP_A + sum(range(N_B))         # 46
EXP_C = N_C * EXP_B + sum(range(N_C))         # 141

A_SETTLE = N_A * K_A + 2 + BRIDGE_HOPS_EST
OFFSET_B = int(math.ceil((A_SETTLE + SETTLE_MARGIN) / 10) * 10)
B_SETTLE = OFFSET_B + N_B * K_B + 2 + BRIDGE_HOPS_EST
OFFSET_C = int(math.ceil((B_SETTLE + SETTLE_MARGIN) / 10) * 10)
print(f"OFFSET_B={OFFSET_B} OFFSET_C={OFFSET_C}")
print(f"expect acc_a={EXP_A} acc_b={EXP_B} acc_c={EXP_C}")

_bctr = 0


def bridge(from_id, from_pos, to_pos, color, hop=8):
    """Chain of signal-each relays, each hop <= `hop` tiles (1 tick latency each).
    Lands its final relay ON to_pos and returns it."""
    global _bctr
    fx, fy = from_pos
    tx, ty = to_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist < 1e-9:
        return from_id, from_pos
    n = max(1, math.ceil(dist / hop))
    pid, ppos = from_id, from_pos
    for h in range(1, n + 1):
        t = h / n
        pos = (fx + (tx - fx) * t, fy + (ty - fy) * t)
        _bctr += 1
        bid = f"br_{_bctr}"
        bp.entities.append(ArithmeticCombinator(id=bid, position=pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each"))
        bp.add_circuit_connection(color, pid, bid, side_1="output", side_2="input")
        pid, ppos = bid, pos
    return pid, ppos


# ============================ STAGE A ====================================
# columns x = 0.5, 3.5, 6.5 ; rows y = 1, 4, 7 (pole row at y=4)
t_ctr_a = ArithmeticCombinator(id="t_ctr_a", position=(0.5, 1.0), first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T")
bp.entities.append(t_ctr_a)
bp.add_circuit_connection(RED, "t_ctr_a", "t_ctr_a", side_1="output", side_2="input")

addr_a = ArithmeticCombinator(id="addr_a", position=(0.5, 4.0), first_operand="signal-T", operation="/", second_operand=K_A, output_signal="signal-D")
bp.entities.append(addr_a)
bp.add_circuit_connection(RED, "t_ctr_a", "addr_a", side_1="output", side_2="input")

tmod_a = ArithmeticCombinator(id="tmod_a", position=(3.5, 1.0), first_operand="signal-T", operation="%", second_operand=K_A, output_signal="signal-M")
bp.entities.append(tmod_a)
bp.add_circuit_connection(RED, "t_ctr_a", "tmod_a", side_1="output", side_2="input")

merge_a = ArithmeticCombinator(id="merge_a", position=(3.5, 4.0), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
bp.entities.append(merge_a)
bp.add_circuit_connection(GREEN, "addr_a", "merge_a", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "tmod_a", "merge_a", side_1="output", side_2="input")

gate_a = DeciderCombinator(
    id="gate_a", position=(6.5, 4.0),
    conditions=[
        DeciderCombinator.Condition(first_signal="signal-M", comparator="=", constant=K_A - 1, compare_type="and"),
        DeciderCombinator.Condition(first_signal="signal-D", comparator="<", constant=N_A, compare_type="and"),
    ],
    outputs=[DeciderCombinator.Output(signal="signal-D", copy_count_from_input=True)],
)
bp.entities.append(gate_a)
bp.add_circuit_connection(GREEN, "merge_a", "gate_a", side_1="output", side_2="input")

acc_a = ArithmeticCombinator(id="acc_a", position=(6.5, 7.0), first_operand="signal-A", operation="+", second_operand="signal-D", output_signal="signal-A")
bp.entities.append(acc_a)
bp.add_circuit_connection(RED, "acc_a", "acc_a", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "gate_a", "acc_a", side_1="output", side_2="input")
A_ACC_POS = (6.5, 7.0)


def shifted_stage(tag, ox, k, n, offset, up_sig, up_id, up_pos,
                  clk_sig, sh_sig, addr_sig, tmod_sig, bval_sig, acc_sig):
    """A stage whose ROM sweep is shifted +offset ticks in time. Reads
    `up_sig` (upstream stage's output value, bridged in on RED), and for
    each address e in 0..n-1 accumulates (up_value + e) into acc_sig.

    Layout (all wires < 9 tiles, pole row at y=4 covers y=1/4/7):
       bval (ox+0.5,4) <- upstream bridge direct-connects from the left
       tctr (ox+3.5,1)  addr (ox+3.5,4)  gate (ox+3.5,7)
       sh   (ox+6.5,1)  tmod (ox+6.5,4)  merge(ox+6.5,7)
       acc  (ox+9.5,7)
    """
    # upstream bridge: travel along y=7 (the row with NO pole line - poles
    # sit at y=4, and a bridge hop landing on y=4 kept failing to revive
    # next to a pole), land left of the stage, then direct-connect up to bval.
    stop = (ox + 0.5 - 3, 7.0)
    up_end_id, up_end_pos = bridge(up_id, up_pos, stop, RED)

    clk = ArithmeticCombinator(id=f"tctr_{tag}", position=(ox + 3.5, 1.0), first_operand=clk_sig, operation="+", second_operand=1, output_signal=clk_sig)
    bp.entities.append(clk)
    bp.add_circuit_connection(RED, f"tctr_{tag}", f"tctr_{tag}", side_1="output", side_2="input")

    sh = ArithmeticCombinator(id=f"sh_{tag}", position=(ox + 6.5, 1.0), first_operand=clk_sig, operation="-", second_operand=offset, output_signal=sh_sig)
    bp.entities.append(sh)
    bp.add_circuit_connection(RED, f"tctr_{tag}", f"sh_{tag}", side_1="output", side_2="input")

    addr = ArithmeticCombinator(id=f"addr_{tag}", position=(ox + 3.5, 4.0), first_operand=sh_sig, operation="/", second_operand=k, output_signal=addr_sig)
    bp.entities.append(addr)
    bp.add_circuit_connection(RED, f"sh_{tag}", f"addr_{tag}", side_1="output", side_2="input")

    tmod = ArithmeticCombinator(id=f"tmod_{tag}", position=(ox + 6.5, 4.0), first_operand=sh_sig, operation="%", second_operand=k, output_signal=tmod_sig)
    bp.entities.append(tmod)
    bp.add_circuit_connection(RED, f"sh_{tag}", f"tmod_{tag}", side_1="output", side_2="input")

    # bval = up_value + addr   (up_value on RED from bridge, addr on GREEN
    # straight from addr_{tag} - one hop, matched below by merge's one hop)
    bval = ArithmeticCombinator(id=f"bval_{tag}", position=(ox + 0.5, 4.0), first_operand=up_sig, operation="+", second_operand=addr_sig, output_signal=bval_sig)
    bp.entities.append(bval)
    bp.add_circuit_connection(RED, up_end_id, f"bval_{tag}", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, f"addr_{tag}", f"bval_{tag}", side_1="output", side_2="input")

    # merge addr+tmod through one relay before the gate: adds the same 1
    # tick that bval's "+addr" hop added, keeping the gate's control (addr,
    # tmod) aligned with the addr baked into bval (cf. Решение 22).
    merge = ArithmeticCombinator(id=f"merge_{tag}", position=(ox + 6.5, 7.0), first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
    bp.entities.append(merge)
    bp.add_circuit_connection(GREEN, f"addr_{tag}", f"merge_{tag}", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, f"tmod_{tag}", f"merge_{tag}", side_1="output", side_2="input")

    gate = DeciderCombinator(
        id=f"gate_{tag}", position=(ox + 3.5, 7.0),
        conditions=[
            DeciderCombinator.Condition(first_signal=tmod_sig, comparator="=", constant=k - 1, compare_type="and"),
            DeciderCombinator.Condition(first_signal=clk_sig, comparator=">=", constant=offset, compare_type="and"),
            DeciderCombinator.Condition(first_signal=addr_sig, comparator="<", constant=n, compare_type="and"),
        ],
        outputs=[DeciderCombinator.Output(signal=bval_sig, copy_count_from_input=True)],
    )
    bp.entities.append(gate)
    bp.add_circuit_connection(GREEN, f"tctr_{tag}", f"gate_{tag}", side_1="output", side_2="input")
    bp.add_circuit_connection(GREEN, f"merge_{tag}", f"gate_{tag}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"bval_{tag}", f"gate_{tag}", side_1="output", side_2="input")

    acc = ArithmeticCombinator(id=f"acc_{tag}", position=(ox + 9.5, 7.0), first_operand=acc_sig, operation="+", second_operand=bval_sig, output_signal=acc_sig)
    bp.entities.append(acc)
    bp.add_circuit_connection(RED, f"acc_{tag}", f"acc_{tag}", side_1="output", side_2="input")
    bp.add_circuit_connection(RED, f"gate_{tag}", f"acc_{tag}", side_1="output", side_2="input")
    return f"acc_{tag}", (ox + 9.5, 7.0)


BX = 30
acc_b_id, acc_b_pos = shifted_stage(
    "b", BX, K_B, N_B, OFFSET_B, up_sig="signal-A", up_id="acc_a", up_pos=A_ACC_POS,
    clk_sig="signal-U", sh_sig="signal-W", addr_sig="signal-E", tmod_sig="signal-N",
    bval_sig="signal-F", acc_sig="signal-B",
)

CX = 65
acc_c_id, acc_c_pos = shifted_stage(
    "c", CX, K_C, N_C, OFFSET_C, up_sig="signal-B", up_id=acc_b_id, up_pos=acc_b_pos,
    clk_sig="signal-V", sh_sig="signal-X", addr_sig="signal-G", tmod_sig="signal-H",
    bval_sig="signal-I", acc_sig="signal-C",
)

# ============================ POWER =====================================
bp.entities.append(ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=(18, 1), buffer_size=10 ** 9))

comb_cols = [0.5, 3.5, 6.5]
for base in (BX, CX):
    comb_cols += [base + 0.5, base + 3.5, base + 6.5, base + 9.5]


def collides(px):
    return any(abs(px - c) < 1.05 for c in comb_cols)


pole_ids = []
px = 2
while px <= CX + 12:
    p = px
    while collides(p):
        p += 1
    pid = f"pole_{len(pole_ids)}"
    bp.entities.append(ElectricPole(name="medium-electric-pole", id=pid, position=(p, 4), quality="legendary"))
    pole_ids.append(pid)
    px = p + 7
for a, b in zip(pole_ids, pole_ids[1:]):
    bp.add_power_connection(a, b)

blueprint_string = bp.to_string()
with open("stage2_chain3_isolated_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)
print(f"Entities: {len(bp.entities)}  (poles: {len(pole_ids)})")
print("Saved stage2_chain3_isolated_test_blueprint.txt")
