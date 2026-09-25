import json

with open("octave_census_expected.json") as f:
    expected = json.load(f)

with open(r"C:\Users\natas\AppData\Roaming\Factorio\script-output\octave_census.json", encoding="utf-8") as f:
    actual = json.load(f)

TOL = 0.6  # Reshenie 26: integer-local-X combinators can land +-0.5 tile off


def match(exp_list, act_list, tol=TOL):
    """Greedy-nearest, not greedy-first: in a dense cluster (several
    combinators within TOL of each other, common in this layout's relay
    chains) matching the FIRST in-tolerance actual point let an earlier
    expected point "steal" a later expected point's real match, producing a
    false MISSING report for the later one and a false EXTRA for whatever
    real point never got claimed - found this the hard way comparing
    v_local's position, which genuinely existed the whole time. Process
    expected points in order of their closest available actual distance
    (globally greedy-nearest-first), not blueprint order, so no expected
    point loses its true match to file-order coincidence."""
    import math
    act_remaining = list(range(len(act_list)))
    candidates = []
    for ei, (ex, ey) in enumerate(exp_list):
        for ai in act_remaining:
            ax, ay = act_list[ai]
            d = math.hypot(ax - ex, ay - ey)
            if abs(ax - ex) < tol and abs(ay - ey) < tol:
                candidates.append((d, ei, ai))
    candidates.sort(key=lambda c: c[0])
    matched_e, matched_a = set(), set()
    for d, ei, ai in candidates:
        if ei in matched_e or ai in matched_a:
            continue
        matched_e.add(ei)
        matched_a.add(ai)
    missing = [exp_list[ei] for ei in range(len(exp_list)) if ei not in matched_e]
    extra = [act_list[ai] for ai in range(len(act_list)) if ai not in matched_a]
    return missing, extra


for name in ("arithmetic-combinator", "decider-combinator", "constant-combinator", "electric-energy-interface"):
    exp = expected.get(name, [])
    act = actual.get(name, [])
    if isinstance(act, dict):
        act = []
    missing, extra = match(exp, act)
    print(f"{name}: expected={len(exp)} actual={len(act)} missing={len(missing)} extra={len(extra)}")
    if missing:
        print(f"  MISSING at: {missing}")
    if extra:
        print(f"  EXTRA (duplicates?) at: {extra}")
