import io
import contextlib

g = {"__name__": "__not_main__"}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(compile(open("export_full.py").read(), "export_full.py", "exec"), g)

bp = g["bp"]
from draftsman.classes.association import Association

# build adjacency for RED wire color specifically among arithmetic/decider
# combinators (RED2 == "red" in this file)
adj = {}
for w in bp.wires:
    e1, c1, e2, c2 = w
    n1 = e1() if isinstance(e1, Association) else e1
    n2 = e2() if isinstance(e2, Association) else e2
    # red wire connector ids are 1 (input) and 2 (output) typically in draftsman's WireConnectorID
    adj.setdefault(n1.id, set()).add(n2.id)
    adj.setdefault(n2.id, set()).add(n1.id)

output_signal_of = g["output_signal_of"]
ALL_OUTPUTS = g["ALL_OUTPUTS"]

# BFS from ALL_OUTPUTS, see which ocol_k are reachable
seen = {ALL_OUTPUTS}
frontier = [ALL_OUTPUTS]
while frontier:
    nxt = []
    for u in frontier:
        for v in adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                nxt.append(v)
    frontier = nxt

reachable_classes = [k for k in range(50) if output_signal_of[k] in seen]
unreachable_classes = [k for k in range(50) if output_signal_of[k] not in seen]
print(f"Reachable from ALL_OUTPUTS ({ALL_OUTPUTS}): {len(reachable_classes)}/50")
print("unreachable classes:", unreachable_classes)
