"""Offline gate for final_io (the in-game chat console + lamp board) with a FAKE model: token letter k ->
NEXT = letter k+1 (one decider per letter), so after "bot: " the fake replies ".,!?'\\"-" and '\\n'.

Checks: the token stream the model sees ("you: <query>\\nbot: " + reply), the reply cells, the pause at the
generated newline, the pixels of board characters (font), the progress bar, a second turn continuing the
conversation, the context-overflow wipe and the RESET button.
  python sim_final_io.py
"""
import sys

from draftsman.entity import DeciderCombinator

from circuit_builder import G, R, Builder, cond, out_const
from circuit_sim import GREEN_IN, RED_IN, RED_OUT, Sim
from final_blocks import CHARS, VOCAB_SIGS
from final_io import BAR, BRST, END, PIX, SEND, place_chat_io
from font5x7 import pixels
from model_blocks import CLK

Tp, Tc, CTX = 30, 20, 256
V = len(VOCAB_SIGS)
TXT = {"h": "hi", "ok": "ok"}


def build():
    B = Builder("io test")
    io = place_chat_io(B, "io_", 0, 0, CTX, Tp, Tc, "signal-P", "signal-W", "signal-R")
    for k in range(V):
        B.comb(DeciderCombinator, f"fake{k}", k, 100, conditions=[cond(VOCAB_SIGS[k], ">", 0, net=G)],
               outputs=[out_const(VOCAB_SIGS[(k + 1) % V], 1)])
        if k:
            B.wire(G, f"fake{k - 1}", f"fake{k}", s1="input", s2="input")
            B.wire(G, f"fake{k - 1}", f"fake{k}", s1="output", s2="output")
    B.link(G, io["token"][0][0], "output", "fake0", "input", "tokfake")
    B.link(G, "fake0", "output", io["next"][0][0], "input", "nextfake")
    B.eei(-10, 0)
    B.connect_power()
    return B, io


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    B, io = build()
    bp, idmap = B.result()
    num = {e["id"]: k + 1 for k, e in enumerate(idmap)}
    unp = B.unpowered()
    print(f"entities {len(idmap)}, unpowered {len(unp)}", sorted({u.split('_')[1] if u.startswith('io_') else u[:4] for u in unp}))
    s = Sim(bp)
    s.settle(500)
    ok = True

    def clock():
        return s.out[num[io["clock"]]].get(CLK, 0)

    def token():
        net = s.net(num["io_mux_0"], 4)            # TOKEN (mux outputs, green)
        return "".join(CHARS[VOCAB_SIGS.index(k)] for k, v in net.items() if v > 0 and k in VOCAB_SIGS) or "∅"

    def set_query(text):
        for k, sid in enumerate(io["slots"]):
            s.set_const(num[sid], {VOCAB_SIGS[CHARS.index(text[k])]: 1} if k < len(text) else {})

    def press(sid, sig):
        s.set_const(num[sid], {sig: 1})
        s.step(3)
        s.set_const(num[sid], {})

    def run_turn(max_ticks=CTX * Tp):
        """Run until the clock stops; returns the tokens seen per position (sampled at phase Tc-2)."""
        seen, still, last = {}, 0, clock()
        for _ in range(max_ticks):
            s.step()
            c = clock()
            if c % Tp == Tc - 2:
                seen[c // Tp] = token()
            still = still + 1 if c == last else 0
            last = c
            if still > 3 * Tp:
                break
        seen[clock() // Tp] = token()               # the paused position (stops before phase Tc-2)
        return seen

    def reply():
        out = []
        for rid in io["reply"]:
            net = s.net(num[rid], GREEN_IN)
            ks = [k for k, v in net.items() if v > 0 and k in VOCAB_SIGS]
            out.append(CHARS[VOCAB_SIGS.index(ks[0])] if len(ks) == 1 else ("∅" if not ks else "?"))
        return "".join(out).rstrip("∅")

    def glyph_ok(prefix, ch):
        net = s.net(num[prefix + "and"], RED_OUT)
        lit = sorted(PIX.index(k) for k, v in net.items() if v > 0)
        return lit == sorted(pixels(ch))

    def check(name, cond_, info=""):
        nonlocal ok
        ok &= bool(cond_)
        print(f"{'OK ' if cond_ else 'BAD'} {name} {info}")

    fake_reply = ".,!?'\"-\n"
    # turn 1
    set_query("hi")
    s.settle(500)
    check("query glyph h", glyph_ok("io_qd0_", "h"))
    check("query glyph i", glyph_ok("io_qd1_", "i"))
    press(io["send"], SEND)
    seen = run_turn()
    stream = "".join(seen[p] for p in sorted(seen))
    exp1 = "you: hi\nbot: " + fake_reply
    check("turn 1 token stream", stream == exp1, repr(stream))
    check("turn 1 reply cells", reply() == fake_reply, repr(reply()))
    check("paused at the generated newline", clock() // Tp == len(exp1) - 1, f"clock {clock()} pos {clock() // Tp}")
    check("reply glyph '.'", glyph_ok("io_r0_", "."))
    check("reply glyph '!'", glyph_ok("io_r2_", "!"))
    bar = s.net(num["io_bgate"], RED_OUT)
    check("progress bar full + green", bar.get(BAR, 0) >= 30 and bar.get("signal-green", 0) == 1, str(bar))
    # turn 2 continues the conversation
    start2 = len(exp1)
    set_query("ok")
    s.settle(500)
    press(io["send"], SEND)
    seen2 = run_turn(Tp * 3)
    bar = s.net(num["io_bgate"], RED_OUT)
    check("progress bar partial + red", 0 < bar.get(BAR, 0) <= 10 and bar.get("signal-red", 0) == 1, str(bar))
    check("reply cleared on send", reply() == "", repr(reply()))
    seen = {**seen2, **run_turn()}
    stream = "".join(seen[p] for p in sorted(seen) if p >= start2 - 1)
    exp2 = "\nyou: ok\nbot: " + fake_reply
    check("turn 2 token stream (continues after the newline)", stream == exp2, repr(stream))
    check("turn 2 reply cells", reply() == fake_reply, repr(reply()))
    # overflow: a 90-char query does not fit after two turns -> wipe, restart from position 0
    long_q = ("abcdefghi " * 9)[:90]
    set_query(long_q)
    s.settle(500)
    press(io["send"], SEND)
    s.step(5)
    check("overflow wipes the clock", clock() < Tp, f"clock {clock()}")
    seen = run_turn()
    stream = "".join(seen[p] for p in sorted(seen))
    exp3 = "you: " + long_q + "\nbot: " + fake_reply
    check("overflow turn from position 0", stream == exp3, repr(stream[:40]) + "...")
    # reset button
    press(io["reset"], BRST)
    s.step(10)
    check("reset clears clock and reply", clock() == 0 and reply() == "", f"clock {clock()} reply {reply()!r}")
    # END mark: "hi" + tick + an old tail "zzz" -> the model reads "hi", the board shows only "HI"
    set_query("hi zzz")
    s.set_const(num[io["slots"][2]], {END: 1})
    s.settle(500)
    check("board shows up to END", glyph_ok("io_qd0_", "h") and glyph_ok("io_qd1_", "i")
          and all(glyph_ok(f"io_qd{k}_", " ") for k in (2, 3, 4, 5)))
    press(io["send"], SEND)
    seen = run_turn()
    stream = "".join(seen[p] for p in sorted(seen))
    check("END: token stream", stream == "you: hi\nbot: " + fake_reply, repr(stream))
    check("no settled int32 overflow", not s.ovf, str(list(s.ovf)[:5]))
    print("SIM FINAL IO", "OK" if ok else "FAILED")


if __name__ == "__main__":
    main()
