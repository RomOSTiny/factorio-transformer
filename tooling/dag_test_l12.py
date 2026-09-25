import sys
from dag_link import build_link, _spine_pts
from dag_lib import LETTERS, wpos, locate
spec = dict(name="L12_logits_argmax",
    src=[("logits", f"olat_0_{o}", "signal-grey") for o in range(4)],
    dst=[("argmax", "logit_in", f"signal-{LETTERS[o]}") for o in range(4)])
resume = None
if len(sys.argv) > 1 and sys.argv[1] == "resume":
    sp = [locate("arithmetic-combinator", *wpos("logits", f"olat_0_{o}"))[:2] for o in range(4)]
    ssp = _spine_pts(sp, 1)
    r = locate("arithmetic-combinator", ssp[0][0], ssp[0][1], tol=3.5)
    print("first relay", r)
    resume = r[2]
build_link(spec, resume_first=resume)
