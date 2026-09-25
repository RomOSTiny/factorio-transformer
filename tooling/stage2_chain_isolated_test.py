"""
Isolated test of the ONE genuinely new mechanism the Sequencer needs that
none of the closed blocks (matmul/LayerNorm/Attention) ever had to solve:
chaining block B's input to block A's LIVE OUTPUT, instead of a Python-time
constant baked into a ConstantCombinator.

Context (see PROJECT.md Решение 37 for the fuller writeup). Every closed
block so far is a self-contained one-shot ROM-driven sweep: its own t_ctr
free-runs from blueprint revival, its accumulators settle to a final value
after LEN*K ticks and hold forever after - but nothing about that design
lets block B read block A's settled value as one of ITS OWN inputs, because
B has NO WAY to know when A is actually done. B's own t_ctr is a completely
independent free-running counter that starts at the same real-world tick
(revival) - if B's own read-window for "the slot that should hold A's
value" happens to land BEFORE A finishes (a real risk: nothing about A's
and B's schedules are related unless deliberately arranged), B permanently
captures A's PARTIAL sum-so-far, not the real answer, and (same as every
other single-shot gate in this project) never gets a second chance.

Decision made here (not the only possible design, but the lowest-risk one -
reuses an already-proven mechanism, doesn't invent a new primitive class):
guard B's capture of A's value with one more AND-condition, EXACTLY the
same multi-condition-AND pattern already proven in gate_j (Решение 26,
matmul-block) and the classifier's argmax (Решение 8/9) - "B's own local
tick counter has reached a build-time-computed OFFSET known to exceed A's
total settle time (with margin)". Pure compile-time arithmetic, same
philosophy as pad_delay/solve_pad_ticks already used everywhere in this
project for in-block timing races - no new live "done" signal, no gating
of t_ctr itself, nothing that hasn't already been proven live.

This file builds THREE things side by side to make the test decisive, not
just "does it look plausible":
  1. Block A - trivial one-shot sweep, same pattern as
     pulse_gate_isolated_test.py, settles acc_A = sum(0..N_A-1) after
     N_A*K_A ticks and holds forever.
  2. captured_good - reads A's live value (bridged in, same bridge()
     helper as every other block) gated on B's own t_ctr reaching OFFSET,
     chosen safely past A's settle point. Expected: matches A's FINAL
     value exactly.
  3. captured_bad - the same wiring, but gated on an EARLY tick chosen to
     land well before A is done. This is a deliberate NEGATIVE CONTROL: if
     it did NOT show a wrong (partial) value, that would mean the whole
     premise ("B can capture stale data if not guarded") was never a real
     risk to begin with, and the offset guard wouldn't be proving anything.
     Expected: does NOT match A's final value (shows whatever partial sum
     A had accumulated by that early tick).
"""
import math

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ArithmeticCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

RED, GREEN = "red", "green"

# ---- Block A: settles to sum(0..N_A-1) after N_A*K_A ticks ----
K_A = 50
N_A = 5
EXPECTED_A_FINAL = sum(range(N_A))  # 0+1+2+3+4 = 10

# ---- Block B's guard ----
SETTLE_MARGIN = 40
OFFSET_GOOD = N_A * K_A + SETTLE_MARGIN  # 290 - safely past A's settle tick
# (~252 at source, ~264 at the far end of the 12-hop bridge); the margin also
# absorbs the few-tick phase uncertainty between the two independent clocks.
TICK_BAD = 185  # deliberately mid-accumulation: A's pulses for addr 0,1,2
# have fired by here (source ticks 49/99/149) but addr 3's (tick 199) has
# NOT, so A's live value is the PARTIAL sum 0+1+2=3, not the final 10. An
# earlier tick that captured 0 would be a degenerate control ("guard
# unnecessary" would look identical to "nothing propagated yet"); a non-zero
# partial is unambiguous. TICK_BAD and TICK_BAD-minus-bridge-latency (~171)
# both sit inside the same inter-pulse gap (149,199), so the captured partial
# is a stable 3 regardless of the exact bridge delay.

# what A's live accumulator actually shows at TICK_BAD, computed the same
# way the circuit will (pulse fires when tmod==K_A-1, i.e. at absolute
# ticks K_A-1, 2*K_A-1, 3*K_A-1, ...; sum whichever have fired by TICK_BAD)
EXPECTED_BAD = sum(a for a in range(N_A) if (a + 1) * K_A - 1 <= TICK_BAD)

bp = Blueprint()
bp.label = "chained-block isolated test (Sequencer prerequisite)"

# --- Block A, origin (0,0) ---
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
        # Found the hard way (live, first build of this test): t_ctr_a never
        # stops - without an explicit upper bound on the address itself,
        # tmod==K_A-1 keeps recurring every K_A ticks FOREVER, so acc_a never
        # "settles", it diverges (keeps summing an ever-growing addr_a). The
        # real matmul-block's gate_j avoids this for free because signal-O
        # only ever equals j once (out_idx sweeps past and never returns) -
        # this simplified single-accumulator test has no such natural bound
        # and needs one added explicitly. Real lesson for the Sequencer: any
        # pulse-driven "settle and hold" latch needs an explicit address
        # upper-bound condition unless the address is ALSO independently
        # single-valued the way out_idx==j is.
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

# --- bridge acc_a's live value 100 tiles over to Block B's territory, same
# relay-chain helper every other block in this project uses ----
_bridge_ctr = 0


def bridge(from_id, from_pos, to_pos, color, hop=8):
    global _bridge_ctr
    fx, fy = from_pos
    tx, ty = to_pos
    dist = math.hypot(tx - fx, ty - fy)
    if dist < 1e-9:
        return from_id, from_pos
    n_hops = max(1, math.ceil(dist / hop))
    prev_id, prev_pos = from_id, from_pos
    for h in range(1, n_hops + 1):
        t = h / n_hops
        pos = (fx + (tx - fx) * t, fy + (ty - fy) * t)
        _bridge_ctr += 1
        bid = f"gbridge_{_bridge_ctr}"
        e = ArithmeticCombinator(id=bid, position=pos, first_operand="signal-each", operation="*", second_operand=1, output_signal="signal-each")
        bp.entities.append(e)
        bp.add_circuit_connection(color, prev_id, bid, side_1="output", side_2="input")
        prev_id, prev_pos = bid, pos
    return prev_id, prev_pos


a_value_id, a_value_pos = bridge("acc_a", (6.5, 7.0), (100.0, 7.0), RED)

# --- Block B, origin (100, 0): its OWN independent free-running clock ----
t_ctr_b = ArithmeticCombinator(id="t_ctr_b", position=(100.5, 1.0), first_operand="signal-T", operation="+", second_operand=1, output_signal="signal-T")
bp.entities.append(t_ctr_b)
bp.add_circuit_connection(RED, "t_ctr_b", "t_ctr_b", side_1="output", side_2="input")

# gate_good: RED carries A's bridged live value (signal-A - acc_a's output
# signal, held constant on the bridge wire), GREEN carries B's own clock
# (signal-T) - condition on GREEN's signal-T, output copies RED's signal-A.
# Two physically separate wires into one decider, same pattern as mult (W on
# one color, X on the other) and gate_j (Решение 26: the value signal is
# routed straight through, control signals live only on the conditions).
# The output signal name MUST match the value actually on the wire (signal-A):
# an earlier version named it signal-D, which is only transiently present
# during A's pulses (via acc_a's self-loop touching gate_a's net) and is
# absent at the gate tick - so copy_count_from_input copied nothing.
gate_good = DeciderCombinator(
    id="gate_good", position=(103.5, 4.0),
    conditions=[DeciderCombinator.Condition(first_signal="signal-T", comparator="=", constant=OFFSET_GOOD, compare_type="and")],
    outputs=[DeciderCombinator.Output(signal="signal-A", copy_count_from_input=True)],
)
bp.entities.append(gate_good)
bp.add_circuit_connection(RED, a_value_id, "gate_good", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "t_ctr_b", "gate_good", side_1="output", side_2="input")

captured_good = ArithmeticCombinator(id="captured_good", position=(103.5, 7.0), first_operand="signal-B", operation="+", second_operand="signal-A", output_signal="signal-B")
bp.entities.append(captured_good)
bp.add_circuit_connection(RED, "captured_good", "captured_good", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "gate_good", "captured_good", side_1="output", side_2="input")

# gate_bad: identical wiring, deliberately early gate tick - the negative
# control (see module docstring). Same signal-A output-name fix as gate_good.
gate_bad = DeciderCombinator(
    id="gate_bad", position=(107.5, 4.0),
    conditions=[DeciderCombinator.Condition(first_signal="signal-T", comparator="=", constant=TICK_BAD, compare_type="and")],
    outputs=[DeciderCombinator.Output(signal="signal-A", copy_count_from_input=True)],
)
bp.entities.append(gate_bad)
bp.add_circuit_connection(RED, a_value_id, "gate_bad", side_1="output", side_2="input")
bp.add_circuit_connection(GREEN, "t_ctr_b", "gate_bad", side_1="output", side_2="input")

captured_bad = ArithmeticCombinator(id="captured_bad", position=(107.5, 7.0), first_operand="signal-C", operation="+", second_operand="signal-A", output_signal="signal-C")
bp.entities.append(captured_bad)
bp.add_circuit_connection(RED, "captured_bad", "captured_bad", side_1="output", side_2="input")
bp.add_circuit_connection(RED, "gate_bad", "captured_bad", side_1="output", side_2="input")

# ---- power: legendary poles, generous radius, same as pulse_gate_isolated_test.py ----
# NB: the old layout put a pole at (0,4), whose collision box overlaps addr_a
# at (0.5,4) - addr_a then deterministically fails to revive() (confirmed
# twice, this session and the previous one). Block A now gets two dedicated
# poles placed in gaps clear of every Block A combinator (footprints are the
# x=[0,1]/[3,4]/[6,7] columns at y=1/4/7); the x=8,16,... row (unchanged,
# every entity on it reads `working` live) covers the bridge and Block B.
eei = ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=(50, 1), buffer_size=10 ** 9)
bp.entities.append(eei)

pole_a1 = ElectricPole(name="medium-electric-pole", id="pole_a1", position=(2, 2.5), quality="legendary")   # covers t_ctr_a/addr_a/tmod_a/merge_a
pole_a2 = ElectricPole(name="medium-electric-pole", id="pole_a2", position=(5, 5.5), quality="legendary")   # covers merge_a/gate_a/acc_a + reaches bridge start
bp.entities.append(pole_a1)
bp.entities.append(pole_a2)

pole_xs = list(range(8, 109, 8))
for i, px in enumerate(pole_xs):
    bp.entities.append(ElectricPole(name="medium-electric-pole", id=f"pole{i}", position=(px, 4), quality="legendary"))
bp.add_power_connection("pole_a1", "pole_a2")
bp.add_power_connection("pole_a2", "pole0")
for i in range(len(pole_xs) - 1):
    bp.add_power_connection(f"pole{i}", f"pole{i + 1}")

blueprint_string = bp.to_string()
with open("stage2_chain_isolated_test_blueprint.txt", "w") as f:
    f.write(blueprint_string)

print(f"Entities: {len(bp.entities)}")
print(f"K_A={K_A} N_A={N_A} -> A settles at tick {N_A * K_A}, EXPECTED acc_a final = {EXPECTED_A_FINAL}")
print(f"OFFSET_GOOD={OFFSET_GOOD} -> EXPECTED captured_good (signal-B) = {EXPECTED_A_FINAL}")
print(f"TICK_BAD={TICK_BAD} -> EXPECTED captured_bad (signal-C) = {EXPECTED_BAD} (must be != {EXPECTED_A_FINAL} to prove the guard matters)")
print("Saved stage2_chain_isolated_test_blueprint.txt")
