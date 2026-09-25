"""Whole-model generator (rehearsal on the dim=32 model; parametric in the config of stage2_weights.json).

Autonomous generation (model_blocks.place_controller): a clock steps positions every Tp ticks; the token of
position P arrives one-hot (its letter signal) on TOKEN, P/W/R on CTRL (W = P+1: the KV cells of position P
are transparent while it is computed); the argmax of position P is captured into token cell P+1 at phase
>= Tc; cells < len(prompt) hold the prompt. Display panels show the token buffer. cmd_src: RUN / RST.
Data flow per layer L:  X_L -> LN1 -> QKV (q red / k green / v green) -> attention (KV cache) -> proj
-> X2 = X_L + proj (pass combinator) -> LN2 -> fc1 (relu) -> fc2 -> X_{L+1} = X2 + fc2 (pass).
Then LN_f -> logits (tok_emb^T, no bias) -> argmax -> next token id (signal-N) + winner letter signal.
Returns the Builder and info (signals, controller ids).
"""
import sys

import numpy as np

sys.argv = sys.argv[:1] if __name__ != "__main__" else sys.argv
import stage2_real_ref as R
from circuit_builder import EACH, G, R as RED, Builder
from dense_attn_lib import SPECIAL, place_dense_attn
from dense_matmul_lib import signal_pool
from model_blocks import CLK, RST, RUN, place_argmax, place_controller, place_dense_matmul, place_embed
from newton_ln_lib import place_newton_ln
from stage2_tokenizer import CHARS, encode

POS_SIG, NEXT_SIG = "signal-P", "signal-N"
W_SIG, R_SIG = "signal-W", "signal-R"          # fixed by dense_attn_lib
DISPLAY = {" ": "_", "\n": "|"}
CHAR_SIG = {".": "signal-letter-dot", ",": "signal-comma", "!": "signal-exclamation-mark", "?": "signal-question-mark",
            "'": "signal-apostrophe", '"': "signal-quotation-mark", "-": "signal-minus", " ": "signal-dot",
            "\n": "signal-rightwards-leftwards-arrow"}
VOCAB_SIGS = [CHAR_SIG.get(ch, f"signal-{ch.upper()}") for ch in CHARS]


def signals(dim, ctx, ffn):
    pool = [s for s in signal_pool(140) if s not in SPECIAL]
    return pool[:dim], pool[dim:dim + ctx], signal_pool(ffn)


def build_model(prompt, ctx=48, Tp=300, Tc=260):
    D, L_N, H, FF = R.DIM, R.LAYERS, R.HEADS, R.FFN
    dims, keys, ffs = signals(D, ctx, FF)
    q = R.q
    b = Builder(f"factorio transformer d{D} L{L_N} h{H} ffn{FF} ctx{ctx}")
    ports = {}

    def P(name):
        return R.P[name]

    def mm(pfx, ox, oy, wname, in_sigs, out_sigs, relu=False, groups=None, bias=True):
        Wt = P(wname + ".weight")                     # torch layout [out][in]
        Wq = q(Wt.T).tolist()
        bs = (q(P(wname + ".bias")) * R.SCALE).tolist() if bias else None
        return place_dense_matmul(b, pfx, ox, oy, Wq, bs, in_sigs, out_sigs, relu=relu, groups=groups)

    def ln(pfx, ox, oy, wname):
        p = place_newton_ln(b, pfx, ox, oy, q(P(wname + ".weight")).tolist(), q(P(wname + ".bias")).tolist(),
                            dims, dims, R.LN_C)
        return dict(xin=[(p["xin"], "input")], out=[(p["out"], "output")])

    def closest(A, Bs):
        return min(((a, c) for a in A for c in Bs), key=lambda ac: np.hypot(*np.subtract(b.pos[ac[0][0]], b.pos[ac[1][0]])))

    def join(color, tag, *groups):
        """Make all members of all groups one network of `color` (links between closest members).
        groups[0] must already be ONE network; every later group is linked to the growing net."""
        net = list(groups[0])
        for k, g in enumerate(groups[1:]):
            (a, sa), (c, sc) = closest(g, net)
            b.link(color, a, sa, c, sc, f"{tag}{k}")
            net += g

    # embed + controller (clock, token buffer, display)
    tokq, posq = q(P("tok_emb.weight")).tolist(), q(P("pos_emb.weight")).tolist()[:ctx]
    emb = place_embed(b, "emb_", 0, 0, tokq, posq, dims, POS_SIG, VOCAB_SIGS)
    ptoks = encode(prompt)
    assert 1 <= len(ptoks) <= ctx and len(ptoks) == len(prompt), "prompt must be in the vocab"
    ctl = place_controller(b, "ctl_", 20, 0, ctx, Tp, Tc, [VOCAB_SIGS[t] for t in ptoks], VOCAB_SIGS,
                           [DISPLAY.get(c, c) for c in CHARS], POS_SIG, W_SIG, R_SIG)
    join(G, "tok", ctl["token"], emb["token"])
    if ctl["tctl_gate"]:
        join(RED, "tctl", ctl["tctl"], ctl["tctl_gate"])
    x_net = emb["out"]
    Y0, BAND = 30, 335
    ctl_ports = []
    for L in range(L_N):
        Y, pre, t = Y0 + L * BAND, f"blocks.{L}.", f"L{L}_"
        ln1 = ln(t + "ln1_", 0, Y, pre + "ln1")
        qkv = mm(t + "qkv_", 12, Y, pre + "qkv", dims, dims * 3, groups=[(D, RED), (D, G), (D, G)])
        att = place_dense_attn(b, t + "att_", 52, Y, dims, keys, R.ATT_C, heads=H, n_cells=ctx)
        proj = mm(t + "proj_", 78, Y, pre + "proj", dims, dims)
        b.arith(t + "pass1", 117, Y + 2, EACH, "+", 0, EACH)
        ln2 = ln(t + "ln2_", 120, Y, pre + "ln2")
        fc1 = mm(t + "fc1_", 132, Y, pre + "fc1", dims, ffs, relu=True)
        fc2 = mm(t + "fc2_", 172, Y, pre + "fc2", ffs, dims)
        b.arith(t + "pass2", 308, Y + 2, EACH, "+", 0, EACH)
        join(RED, t + "x", x_net, ln1["xin"], [(t + "pass1", "input")])
        join(RED, t + "h1", ln1["out"], qkv["xin"])
        join(RED, t + "q", qkv["outs"][0], [(att["q_in"], None)])
        join(G, t + "k", qkv["outs"][1], [(k, "input") for k in att["k_in"]])
        join(G, t + "v", qkv["outs"][2], [(v, "input") for v in att["v_in"]])
        join(RED, t + "a", [(att["att_out"], "output")], proj["xin"])
        join(RED, t + "x2", proj["outs"][0], [(t + "pass1", "output")], ln2["xin"], [(t + "pass2", "input")])
        join(RED, t + "h2", ln2["out"], fc1["xin"])
        join(RED, t + "f1", fc1["outs"][0], fc2["xin"])
        ctl_ports.append([(att["ctl"], None)])
        join(RED, t + "x3", fc2["outs"][0], [(t + "pass2", "output")])
        x_net = fc2["outs"][0] + [(t + "pass2", "output")]
    join(RED, "ctl", ctl["ctrl"], ctl["ctrl_mux"], emb["ctrl"], *ctl_ports)
    Y = Y0 + L_N * BAND
    lnf = ln("lnf_", 0, Y, "ln_f")
    logit = place_dense_matmul(b, "logits_", 12, Y, q(P("tok_emb.weight")).T.tolist(), None, dims, VOCAB_SIGS)
    arg = place_argmax(b, "arg_", 52, Y, VOCAB_SIGS, NEXT_SIG)
    join(RED, "xf", x_net, lnf["xin"])
    join(RED, "lf", lnf["out"], logit["xin"])
    join(RED, "lg", logit["outs"][0], arg["logits"])
    if ctl["next"]:
        join(G, "next", arg["onehot"], ctl["next"])
    for name, port, x in (("next_sink", "next", 52), ("letter_sink", "letter", 54), ("logits_sink", None, 50)):
        b.const(name, x, Y + 8, {})
        src = arg[port] if port else logit["outs"][0]
        (a, sa), _ = closest(src, [(name, None)])
        b.link(RED, a, sa, name, None, name)
    b.eei(60, Y + 4)
    added = b.connect_power()
    return b, dict(dims=dims, keys=keys, ffs=ffs, vocab=VOCAB_SIGS, power_links_added=added, prompt=prompt,
                   ctx=ctx, Tp=Tp, Tc=Tc, cmd="ctl_cmd_src", clock="ctl_clk_acc", signals=dict(
                       pos=POS_SIG, next=NEXT_SIG, w=W_SIG, r=R_SIG, clk=CLK, run=RUN, rst=RST))


if __name__ == "__main__":
    import json
    import time
    import warnings
    caught = []
    warnings.showwarning = lambda m, *a, **k: caught.append(str(m))
    t0 = time.time()
    prompt = sys.argv[1] if len(sys.argv) > 1 else "one day, a little girl "
    b, info = build_model(prompt)
    t1 = time.time()
    unp = b.unpowered()
    bp_string, idmap = b.result()
    t2 = time.time()
    open("model_blueprint.txt", "w").write(bp_string)
    json.dump(idmap, open("model_ids.json", "w"))
    json.dump(info, open("model_info.json", "w"))
    names = {}
    for e in idmap:
        names[e["name"]] = names.get(e["name"], 0) + 1
    xs = [e["x"] for e in idmap]; ys = [e["y"] for e in idmap]
    print(f"entities {len(idmap)} {names}")
    print(f"route poles {b.n_route_poles}, power links added {info['power_links_added']}, unpowered {len(unp)} {unp[:5]}")
    print(f"bbox x {min(xs)}..{max(xs)} y {min(ys)}..{max(ys)}; build {t1 - t0:.0f}s, to_string {t2 - t1:.0f}s, warnings {len(caught)}")
    for w in caught[:5]:
        print("  ", w[:200])
