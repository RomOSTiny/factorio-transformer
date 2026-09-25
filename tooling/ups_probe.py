"""Measure the MAX update rate of the running game: game.speed is raised so the game runs as fast as it
can, ticks per wall-clock second = max UPS; game.speed is always restored to 1.

  python ups_probe.py [seconds] [--count]     --count also counts combinators on the whole surface
"""
import json
import sys
import time

import rcon_client

SECS = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else 15.0
c = rcon_client.connect(timeout=300.0)


def cmd(body):
    return c.command("/c " + body).strip()


if "--count" in sys.argv:
    print(cmd('local s = game.surfaces["nauvis"]; local t = {}; '
              'for _, ty in pairs({"arithmetic-combinator", "decider-combinator", "constant-combinator", "selector-combinator", '
              '"electric-pole"}) do t[ty] = s.count_entities_filtered{type=ty} end; t.all = s.count_entities_filtered{force="player"}; '
              'rcon.print(helpers.table_to_json(t))'))
try:
    cmd("game.speed = 1000")
    time.sleep(2.0)                                   # let it spin up
    t0, k0 = time.time(), int(cmd("rcon.print(game.tick)"))
    time.sleep(SECS)
    t1, k1 = time.time(), int(cmd("rcon.print(game.tick)"))
finally:
    cmd("game.speed = 1")
ups = (k1 - k0) / (t1 - t0)
print(json.dumps({"max_ups": round(ups, 1), "ms_per_tick": round(1000 / ups, 2), "ticks": k1 - k0, "secs": round(t1 - t0, 1)}))
c.close()
