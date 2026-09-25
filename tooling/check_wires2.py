import io
import contextlib

g = {"__name__": "__not_main__"}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(compile(open("export_full.py").read(), "export_full.py", "exec"), g)

bp = g["bp"]
from draftsman.classes.association import Association

adj = {}
for w in bp.wires:
    e1, c1, e2, c2 = w
    n1 = e1() if isinstance(e1, Association) else e1
    n2 = e2() if isinstance(e2, Association) else e2
    adj.setdefault(n1.id, set()).add(n2.id)
    adj.setdefault(n2.id, set()).add(n1.id)

hidden_pool_id = g["hidden_pool_id"]
seen = {hidden_pool_id}
frontier = [hidden_pool_id]
while frontier:
    nxt = []
    for u in frontier:
        for v in adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                nxt.append(v)
    frontier = nxt

# check: are all omul_k_j entities reachable from hidden_pool?
missing = []
total = 0
for k in range(50):
    for j in range(32):
        mid = f"omul_{k}_{j}"
        total += 1
        if mid not in seen:
            missing.append(mid)

print(f"reachable from hidden_pool: {len(seen)} nodes total")
print(f"omul entities: {total}, unreachable: {len(missing)}")
print("sample unreachable:", missing[:10])

# also check: is hidden_pool_id's OWN output wired to anything at all?
print(f"\nhidden_pool_id direct neighbors: {adj.get(hidden_pool_id, set())}")
