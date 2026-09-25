import io
import contextlib

g = {"__name__": "__not_main__"}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(compile(open("export_full.py").read(), "export_full.py", "exec"), g)

bp = g["bp"]
from draftsman.classes.association import Association

# build DIRECTED graph this time: output_side -> input_side (the direction
# a value actually flows), separately from input_side -> output_side
# doesn't exist (values don't flow backward through an entity)
out_to_in = {}  # entity_id -> set of entity_ids it feeds (via its output)
for w in bp.wires:
    e1, c1, e2, c2 = w
    n1 = e1() if isinstance(e1, Association) else e1
    n2 = e2() if isinstance(e2, Association) else e2
    # c1/c2 are WireConnectorID values: 1=input_red,2=input_green,3=output_red,4=output_green
    c1v = c1.value if hasattr(c1, "value") else c1
    c2v = c2.value if hasattr(c2, "value") else c2
    if c1v in (3, 4) and c2v in (1, 2):
        out_to_in.setdefault(n1.id, set()).add(n2.id)
    elif c2v in (3, 4) and c1v in (1, 2):
        out_to_in.setdefault(n2.id, set()).add(n1.id)
    # NOTE: constant combinators aren't "dual circuit connectable" - their
    # single circuit connector is used for both add_circuit_connection
    # sides in this file's code (side_2 only). Treat those separately if
    # needed; skip for this specific cycle search.

# Now: does hidden_pool's own OUTPUT eventually feed back into hidden_pool's
# own INPUT? (a self-loop of any length). DFS from hidden_pool's OUTPUT
# targets, looking for a path back to hidden_pool_id itself.
hidden_pool_id = g["hidden_pool_id"]
start_targets = out_to_in.get(hidden_pool_id, set())
seen = set()
stack = list(start_targets)
found_cycle = False
parent = {}
while stack:
    u = stack.pop()
    if u == hidden_pool_id:
        found_cycle = True
        break
    if u in seen:
        continue
    seen.add(u)
    for v in out_to_in.get(u, ()):
        if v not in seen:
            parent[v] = u
            stack.append(v)

print(f"directed edges: {sum(len(v) for v in out_to_in.values())}")
print(f"reachable (directed, from hidden_pool's output) : {len(seen)}")
print(f"does hidden_pool feed back into itself (cycle)?: {found_cycle}")

# also: general cycle detection anywhere in the directed graph (DFS with
# recursion stack), limited scope near the gbridge chain of interest
def find_any_cycle(start):
    visited = set()
    rec_stack = []
    rec_set = set()

    def dfs(u):
        visited.add(u)
        rec_stack.append(u)
        rec_set.add(u)
        for v in out_to_in.get(u, ()):
            if v not in visited:
                result = dfs(v)
                if result:
                    return result
            elif v in rec_set:
                return rec_stack[rec_stack.index(v):] + [v]
        rec_stack.pop()
        rec_set.discard(u)
        return None

    return dfs(start)


import sys
sys.setrecursionlimit(10000)
cyc = find_any_cycle(hidden_pool_id)
print(f"\nany cycle reachable from hidden_pool (directed DFS): {cyc[:15] if cyc else None}")
if cyc:
    print(f"cycle length: {len(cyc)}")
