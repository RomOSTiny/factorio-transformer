"""Read every block's output latches and compare with stage2_sequencer_ref.json."""
import json, sys
from dag_lib import LUA_LIB, block, lua

SEQ = json.load(open("stage2_sequencer_ref.json"))
START_TICK = int(sys.argv[1]) if len(sys.argv) > 1 else None
SPEC = {  # block: (latch prefix, signal, expected[p][o], positions)
    "embed": ("elat_", "signal-grey", SEQ["x_fp"]),
    "ln_attn": ("h1lat_", "signal-X", SEQ["h1_fp"]),
    "qkv": ("olat_", "signal-grey", [SEQ["q_fp"][p] + SEQ["k_fp"][p] + SEQ["v_fp"][p] for p in range(2)]),
    "attn": ("alat_", "signal-grey", SEQ["attn_out_fp"]),
    "proj": ("olat_", "signal-grey", SEQ["proj_fp"]),
    "res1": ("olat_", "signal-grey", SEQ["x2_fp"]),
    "ln_ffn": ("h1lat_", "signal-X", SEQ["h2_fp"]),
    "fc1": ("olat_", "signal-grey", SEQ["fc1_fp"]),
    "fc2": ("olat_", "signal-grey", SEQ["fc2_fp"]),
    "res2": ("olat_", "signal-grey", SEQ["x3_fp"]),
    "ln_final": ("h1lat_", "signal-X", SEQ["xf_fp"]),
    "logits": ("olat_", "signal-grey", [SEQ["logits_fp"]]),
}
tick = lua("rcon.print(game.tick)").strip()
print("tick", tick, ("elapsed %d" % (int(tick) - START_TICK)) if START_TICK else "")
allok = True
for name, (pref, sig, exp) in SPEC.items():
    b = block(name)
    cells = []
    for p in range(len(exp)):
        for o in range(len(exp[0])):
            x, y, _ = b["ids"][f"{pref}{p}_{o}"]
            cells.append((p, o, x, y))
    arr = ",".join(f"{{{p},{o},{x},{y}}}" for p, o, x, y in cells)
    body = f'''
local cells = {{{arr}}}
local out = {{}}
for _, c in ipairs(cells) do
  local best, bd = nil, 1e9
  for _, e in pairs(S.find_entities_filtered{{area={{{{c[3]-1.2,c[4]-1.2}},{{c[3]+1.2,c[4]+1.2}}}}, name="arithmetic-combinator"}}) do
    local d = (e.position.x-c[3])^2 + (e.position.y-c[4])^2
    if d < bd then bd = d best = e end
  end
  local v = 0
  if best then
    local sg = best.get_signals(ROUT, defines.wire_connector_id.combinator_output_green)
    if sg then for _, s2 in pairs(sg) do if s2.signal.name == "{sig}" then v = s2.count end end end
  else v = -99999 end
  out[#out+1] = v
end
rcon.print(helpers.table_to_json(out))
'''
    got = json.loads(lua(LUA_LIB + body).strip())
    n = len(exp[0])
    gotm = [got[p * n:(p + 1) * n] for p in range(len(exp))]
    ok = gotm == exp
    allok &= ok
    print(f"{name:9s} {'OK ' if ok else 'BAD'} got={gotm}" + ("" if ok else f" exp={exp}"))
t = lua(LUA_LIB + '''
local best = "-"
for _, e in pairs(S.find_entities_filtered{area={{10985,4190},{11010,4215}}, type="decider-combinator"}) do
  local sg = e.get_signals(ROUT)
  if sg then for _, s2 in pairs(sg) do if s2.signal.name == "signal-T" then best = s2.count end end end
end
rcon.print(best)
''').strip()
print("argmax signal-T =", t, "(expected", SEQ["next_token"], ")")
print("ALL OK" if allok and t == str(SEQ["next_token"]) else "not yet / mismatch")
