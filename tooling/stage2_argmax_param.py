"""Argmax block for the Sequencer DAG: winner-take-all over VOCAB logits.

Reuses the pairwise-decider argmax pattern already proven in
export_full.py's Stage-1 classifier (build_argmax, live-verified there
for N=49) and in Attention's max_ge/max_lt: one decider per candidate
index k with (VOCAB-1) AND'd conditions comparing logit[k] against every
other logit (">=" for higher indices, ">" for lower, so ties break toward
the lowest index and exactly one decider ever fires). Purely combinational
(like LayerNorm) - the logits are only ever computed for the last
sequence position, so there is nothing to time-multiplex here; given
stable inputs the winning decider's output just holds.
"""
import json

from draftsman.classes.blueprint import Blueprint
from draftsman.entity import ConstantCombinator, DeciderCombinator, ElectricEnergyInterface, ElectricPole

RED = "red"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

with open("stage2_sequencer_ref.json") as f:
    SEQ = json.load(f)

LOGITS = SEQ["logits_fp"]
EXPECTED = SEQ["next_token"]
VOCAB = len(LOGITS)
assert VOCAB <= len(LETTERS)
LOGIT_SIGS = [f"signal-{LETTERS[i]}" for i in range(VOCAB)]
OUT_SIG = "signal-T"

bp = Blueprint()
bp.label = "Argmax parametrized (winner-take-all over VOCAB logits, live input buffer)"

lin = ConstantCombinator(id="logit_in", position=(0, 0))
for i in range(VOCAB):
    lin.set_signal(index=i, name=LOGIT_SIGS[i], count=LOGITS[i])
bp.entities.append(lin)

arg_ids = []
for k in range(VOCAB):
    conditions = []
    for other in range(VOCAB):
        if other == k:
            continue
        comparator = ">=" if other > k else ">"
        conditions.append(DeciderCombinator.Condition(
            first_signal=LOGIT_SIGS[k], comparator=comparator, second_signal=LOGIT_SIGS[other], compare_type="and",
        ))
    aid = f"argmax_{k}"
    bp.entities.append(DeciderCombinator(
        id=aid, position=(k * 2, 4),
        conditions=conditions,
        outputs=[DeciderCombinator.Output(signal=OUT_SIG, copy_count_from_input=False, constant=k)],
    ))
    bp.add_circuit_connection(RED, "logit_in", aid, side_2="input")
    if k > 0:
        bp.add_circuit_connection(RED, arg_ids[-1], aid, side_1="output", side_2="output")
    arg_ids.append(aid)

sub = ElectricPole(name="substation", id="sub_0", position=(3, 2), quality="legendary")
bp.entities.append(sub)
eei = ElectricEnergyInterface(name="electric-energy-interface", id="power_source", position=(3, 6), buffer_size=10**9)
bp.entities.append(eei)

bp_string = bp.to_string()

with open("stage2_argmax_param_blueprint.txt", "w") as f:
    f.write(bp_string)

idmap = []
for e in bp.entities:
    eid = getattr(e, "id", None)
    if not eid:
        continue
    idmap.append({"id": eid, "x": round(e.position.x, 3), "y": round(e.position.y, 3), "name": e.name})
with open("stage2_argmax_param_ids.json", "w") as f:
    json.dump(idmap, f)

print(f"entities: {len(bp.entities)}")
print(f"LOGITS={LOGITS} EXPECTED next_token={EXPECTED}")
print("Saved stage2_argmax_param_blueprint.txt")
