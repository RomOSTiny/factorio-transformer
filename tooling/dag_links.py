"""All DAG links of the smoke model. Usage: python dag_links.py L2 L3q ..."""
import sys
from dag_link import build_link
from dag_lib import LETTERS

G, X = "signal-grey", "signal-X"
def sig(i): return f"signal-{LETTERS[i]}"
P2, D4 = range(2), range(4)

LINKS = {
 "L1a": dict(name="L1a_embed_lnattn", src=[("embed", f"elat_{p}_{d}", G) for p in P2 for d in D4], dst=[("ln_attn", f"xbuf_{p}_{d}", sig(d)) for p in P2 for d in D4]),
 "L1b": dict(name="L1b_embed_res1", src=[("embed", f"elat_{p}_{d}", G) for p in P2 for d in D4], dst=[("res1", f"xbuf_{p}_{d}", sig(d)) for p in P2 for d in D4]),
 "L2": dict(name="L2_lnattn_qkv", src=[("ln_attn", f"h1lat_{p}_{i}", X) for p in P2 for i in D4], dst=[("qkv", f"xbuf_{p}_{i}", sig(i)) for p in P2 for i in D4]),
 "L3q": dict(name="L3q_qkv_attnQ", src=[("qkv", f"olat_{p}_{i}", G) for p in P2 for i in D4], dst=[("attn", f"qbuf_{p}_{i}", sig(i)) for p in P2 for i in D4]),
 "L3k": dict(name="L3k_qkv_attnK", src=[("qkv", f"olat_{p}_{4+i}", G) for p in P2 for i in D4], dst=[("attn", f"c_K{p}_{i}", sig(4 + 4 * p + i)) for p in P2 for i in D4]),
 "L3v": dict(name="L3v_qkv_attnV", src=[("qkv", f"olat_{p}_{8+i}", G) for p in P2 for i in D4], dst=[("attn", f"c_V{p}_{i}", sig(12 + 4 * p + i)) for p in P2 for i in D4]),
 "L4": dict(name="L4_attn_proj", src=[("attn", f"alat_{p}_{i}", G) for p in P2 for i in D4], dst=[("proj", f"xbuf_{p}_{i}", sig(i)) for p in P2 for i in D4]),
 "L5": dict(name="L5_proj_res1", src=[("proj", f"olat_{p}_{o}", G) for p in P2 for o in D4], dst=[("res1", f"xbuf_{p}_{4+o}", sig(4 + o)) for p in P2 for o in D4]),
 "L6a": dict(name="L6a_res1_lnffn", src=[("res1", f"olat_{p}_{o}", G) for p in P2 for o in D4], dst=[("ln_ffn", f"xbuf_{p}_{o}", sig(o)) for p in P2 for o in D4]),
 "L6b": dict(name="L6b_res1_res2", src=[("res1", f"olat_{p}_{o}", G) for p in P2 for o in D4], dst=[("res2", f"xbuf_{p}_{o}", sig(o)) for p in P2 for o in D4]),
 "L7": dict(name="L7_lnffn_fc1", src=[("ln_ffn", f"h1lat_{p}_{i}", X) for p in P2 for i in D4], dst=[("fc1", f"xbuf_{p}_{i}", sig(i)) for p in P2 for i in D4]),
 "L8": dict(name="L8_fc1_fc2", src=[("fc1", f"olat_{p}_{o}", G) for p in P2 for o in range(8)], dst=[("fc2", f"xbuf_{p}_{o}", sig(o)) for p in P2 for o in range(8)]),
 "L9": dict(name="L9_fc2_res2", src=[("fc2", f"olat_{p}_{o}", G) for p in P2 for o in D4], dst=[("res2", f"xbuf_{p}_{4+o}", sig(4 + o)) for p in P2 for o in D4]),
 "L10": dict(name="L10_res2_lnfinal", src=[("res2", f"olat_{p}_{o}", G) for p in P2 for o in D4], dst=[("ln_final", f"xbuf_{p}_{o}", sig(o)) for p in P2 for o in D4]),
 "L11": dict(name="L11_lnfinal_logits", src=[("ln_final", f"h1lat_1_{i}", X) for i in D4], dst=[("logits", f"xbuf_0_{i}", sig(i)) for i in D4]),
}

if __name__ == "__main__":
    for k in sys.argv[1:]:
        print("=====", k)
        build_link(LINKS[k])
