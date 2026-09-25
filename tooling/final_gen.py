"""Generator of the FINAL model: the delivered d=256 / 8 layers / 8 heads / ffn 1024 / ctx 256 model
(E:\\dev\\modelgame\\delivery) as ONE blueprint. Semantics: final_ref.IntModel (checked by final_block_test,
sim_final_attn, sim_final_run).

Same autonomous-generation scheme as the rehearsal (model_gen / Reshenie 47): the clock steps positions every
Tp ticks; the token of position P arrives one-hot on TOKEN (green), P / W = P+1 / R on CTRL (red); the argmax
of position P is captured into token cell P+1 at phase >= Tc. The player talks to it in game through
final_io (query console of constant combinators, SEND / RESET, lamp board), placed above the model (IO_Y).
Layout: embed on top (y < Y0), then the 8 layer bands side by side (band L at x = L*BAND_W):
  LN1 (0) -> QKV (12, 3 columns q/k/v) -> attention (24) -> proj (55) -> pass1 (60) -> LN2 (62)
  -> fc1 (74, 4 columns, relu) -> fc2 (88) -> pass2 (93)
then LN_f -> logits (tok_emb^T, no bias) -> argmax to the right of the last band.
"""
import sys

import numpy as np

import final_ref as F
from circuit_builder import EACH, G, R, Builder
from final_attn_lib import W_SIG, R_SIG, place_final_attn
from final_blocks import CHARS, VOCAB_SIGS, data_signals, place_final_ln, place_vec_matmul
from final_io import place_chat_io
from model_blocks import CLK, RST, RUN, place_argmax, place_embed

POS_SIG, NEXT_SIG = "signal-P", "signal-N"
DISPLAY = {" ": "_", "\n": "|"}
Y0, BAND_W = 80, 100
IO_Y = -110                     # the chat console + lamp board above the model


def build_final(Tp=420, Tc=360, layers=None, M=None):
    """layers: build only the first n layers (tests); M: an IntModel (loaded once by the caller)."""
    M = M or F.IntModel()
    D, H, FF, ctx = M.dim, M.heads, M.ffn, M.ctx
    L_N = M.layers if layers is None else layers
    dims, keys, ffs = data_signals(D, ctx, FF)
    b = Builder(f"factorio transformer final d{D} L{L_N} h{H} ffn{FF} ctx{ctx}")

    def closest(A, Bs):
        return min(((a, c) for a in A for c in Bs), key=lambda ac: np.hypot(*np.subtract(b.pos[ac[0][0]], b.pos[ac[1][0]])))

    def join(color, tag, *groups):
        """Make all members of all groups one network of `color` (link each later group to the growing net)."""
        net = list(groups[0])
        for k, g in enumerate(groups[1:]):
            (a, sa), (c, sc) = closest(g, net)
            b.link(color, a, sa, c, sc, f"{tag}{k}")
            net += g

    def mm(pfx, ox, oy, wb, in_sigs, out_sigs, relu=False, groups=None, bias=True):
        W, bias_q = wb
        return place_vec_matmul(b, pfx, ox, oy, W.T.tolist(), (bias_q * 100).tolist() if bias else None, in_sigs,
                                out_sigs, relu=relu, groups=groups)

    def ln(pfx, ox, oy, gb):
        return place_final_ln(b, pfx, ox, oy, gb[0], gb[1], dims, F.LN_EPS_Q)

    # embed + controller
    emb = place_embed(b, "emb_", 0, 0, M.tok_u.tolist(), M.pos_u.tolist()[:ctx], dims, POS_SIG, VOCAB_SIGS)
    ctl = place_chat_io(b, "io_", 0, IO_Y, ctx, Tp, Tc, POS_SIG, W_SIG, R_SIG)
    join(G, "tok", ctl["token"], emb["token"])
    x_net = emb["out"]
    ctl_ports = []
    steps = M.exp_steps()
    for L in range(L_N):
        X, t, Lw = L * BAND_W, f"L{L}_", M.L[L]
        ln1 = ln(t + "ln1_", X, Y0 + 6, Lw["ln1"])
        qkv = mm(t + "qkv_", X + 12, Y0 + 12, Lw["qkv"], dims, dims * 3, groups=[(D, R), (D, R), (D, R)])
        att = place_final_attn(b, t + "att_", X + 24, Y0, dims, keys, steps, F.ATT_OFF, heads=H, n_cells=ctx)
        proj = mm(t + "proj_", X + 55, Y0 + 12, Lw["proj"], dims, dims)
        b.arith(t + "pass1", X + 60, Y0 + 8, EACH, "+", 0, EACH)
        ln2 = ln(t + "ln2_", X + 62, Y0 + 6, Lw["ln2"])
        fc1 = mm(t + "fc1_", X + 74, Y0 + 12, Lw["fc1"], dims, ffs, relu=True)
        fc2 = mm(t + "fc2_", X + 88, Y0 + 12, Lw["fc2"], ffs, dims)
        b.arith(t + "pass2", X + 93, Y0 + 8, EACH, "+", 0, EACH)
        join(R, t + "x", x_net, ln1["xin"], [(t + "pass1", "input")])
        join(R, t + "h1", ln1["outs"][0], qkv["xin"])
        join(R, t + "q", qkv["outs"][0], [(att["q_in"], None)])
        join(G, t + "k", qkv["outs"][1], [(k, "input") for k in att["k_in"]])
        join(G, t + "v", qkv["outs"][2], [(v, "input") for v in att["v_in"]])
        join(R, t + "a", [(att["att_out"], "output")], proj["xin"])
        join(R, t + "x2", proj["outs"][0], [(t + "pass1", "output")], ln2["xin"], [(t + "pass2", "input")])
        join(R, t + "h2", ln2["outs"][0], fc1["xin"])
        join(R, t + "f1", fc1["outs"][0], fc2["xin"])
        join(R, t + "x3", fc2["outs"][0], [(t + "pass2", "output")])
        ctl_ports.append([(att["ctl"], None)])
        x_net = fc2["outs"][0] + [(t + "pass2", "output")]
    join(R, "ctl", ctl["ctrl"], emb["ctrl"], *ctl_ports)
    X = L_N * BAND_W
    lnf = ln("lnf_", X, Y0 + 6, M.lnf)
    logit = place_vec_matmul(b, "logits_", X + 12, Y0 + 12, M.emb_q.tolist(), None, dims, VOCAB_SIGS)
    arg = place_argmax(b, "arg_", X + 18, Y0 + 8, VOCAB_SIGS, NEXT_SIG)
    join(R, "xf", x_net, lnf["xin"])
    join(R, "lf", lnf["outs"][0], logit["xin"])
    join(R, "lg", logit["outs"][0], arg["logits"])
    if ctl["next"]:
        join(G, "next", arg["onehot"], ctl["next"])
    for name, port, x in (("next_sink", "next", X + 18), ("letter_sink", "letter", X + 20), ("logits_sink", None, X + 16)):
        b.const(name, x, Y0 + 2, {})
        src = arg[port] if port else logit["outs"][0]
        (a, sa), _ = closest(src, [(name, None)])
        b.link(R, a, sa, name, None, name)
    b.eei(X + 26, Y0 + 2)
    added = b.connect_power()
    return b, dict(dims=dims, keys=keys, ffs=ffs, vocab=VOCAB_SIGS, power_links_added=added,
                   ctx=ctx, Tp=Tp, Tc=Tc, layers=L_N, cmd=ctl["cmd"], clock=ctl["clock"], send=ctl["send"],
                   reset=ctl["reset"], slots=ctl["slots"], reply=ctl["reply"], signals=dict(
                       pos=POS_SIG, next=NEXT_SIG, w=W_SIG, r=R_SIG, clk=CLK, run=RUN, rst=RST))


if __name__ == "__main__":
    import json
    import time
    import warnings
    caught = []
    warnings.showwarning = lambda m, *a, **k: caught.append(str(m))
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    b, info = build_final()
    t1 = time.time()
    unp = b.unpowered()
    bp_string, idmap = b.result()
    t2 = time.time()
    open("final_blueprint.txt", "w").write(bp_string)
    json.dump(idmap, open("final_ids.json", "w"))
    json.dump(info, open("final_info.json", "w"))
    names = {}
    for e in idmap:
        names[e["name"]] = names.get(e["name"], 0) + 1
    xs = [e["x"] for e in idmap]; ys = [e["y"] for e in idmap]
    print(f"entities {len(idmap)} {names}")
    print(f"route poles {b.n_route_poles}, power links added {info['power_links_added']}, unpowered {len(unp)} {unp[:5]}")
    print(f"bbox x {min(xs)}..{max(xs)} y {min(ys)}..{max(ys)}; build {t1 - t0:.0f}s, to_string {t2 - t1:.0f}s, "
          f"blueprint {len(bp_string) / 1e6:.1f} MB, warnings {len(caught)}")
    for w in caught[:5]:
        print("  ", w[:200])
