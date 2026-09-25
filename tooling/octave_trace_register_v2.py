"""
Fix for octave_tctr_rewire_and_trace_cmd.txt's runtime crash: t_ctr's
rewiring succeeded (confirmed printed message + tctr_wires in
octave_tctr_rewire.json), so this command must NOT touch t_ctr/addr/tmod
wiring again. The crash was purely a bug in THIS script's own missing-
entity check: `E[name]=cands[1]` when cands is empty sets E[name]=nil,
and in Lua a nil-valued table entry simply doesn't exist for `pairs()` -
so the "for k,v in pairs(E) do if not v" check silently missed whichever
of value_bc/ol_local/s_e (most likely candidates, since t_ctr/addr/tmod
already proven found) failed to resolve, and the on_tick handler crashed
on `w.e.valid` for a nil `e` field - the game then disabled the level
script (single error dialog, not a per-tick spam, matches what happened).

This version: (a) checks an EXPLICIT list of expected names against E
(catches real gaps, not fooled by Lua's nil-key semantics), (b) widens the
search radius for value_bc/ol_local/s_e from 1.3 to 4 tiles in case a
live collision/repair shifted one of them further than expected (their
local positions are all already non-integer per source, so the known
+0.5-integer-shift mechanism shouldn't apply, but the source's own
comments warn these specific three had real live-collision history), and
(c) reports exactly which candidates it found (not just a boolean) so if
something's still off, the next round has real data instead of a guess.
Does NOT touch t_ctr/addr/tmod at all - only reads addr for signal-D.
"""
OX, OY = 94.0, -156.0

UNITS = {
    "read_0": 1345, "read_1": 1351, "read_2": 1357, "read_3": 1361,
    "crelay_0_1": 1360,
    "read_7": 1522, "read_8": 1465,
    "crelay_1_1": 1521, "crelay_2_1": 1524,
}

# (label, local_x, local_y, radius)
FIND_BY_POS = [
    ("addr", 0.5, 4.0, 1.3),
    ("value_bc", 230.5, -10.0, 4.0),
    ("ol_local", 245.5, 301.0, 4.0),
    ("s_e", 250.5, 304.0, 4.0),
]

ALL_NAMES = list(UNITS.keys()) + [n for n, *_ in FIND_BY_POS]

units_lua = "{" + ",".join(f'{k}={v}' for k, v in UNITS.items()) + "}"
find_lua = "{" + ",".join(f'{{name="{n}",x={x + OX},y={y + OY},r={r}}}' for n, x, y, r in FIND_BY_POS) + "}"
names_lua = "{" + ",".join(f'"{n}"' for n in ALL_NAMES) + "}"

cmd = (
    '/c local surf=game.player.surface; '
    'local U=' + units_lua + '; '
    'local E={}; for k,u in pairs(U) do E[k]=game.get_entity_by_unit_number(u) end; '
    'local fb=' + find_lua + '; '
    'local dbg={}; '
    'for _,tg in pairs(fb) do '
    'local cands=surf.find_entities_filtered{area={{tg.x-tg.r,tg.y-tg.r},{tg.x+tg.r,tg.y+tg.r}}, type="arithmetic-combinator"}; '
    'local names={}; for _,c in pairs(cands) do table.insert(names, {x=c.position.x,y=c.position.y,unit=c.unit_number}) end; '
    'dbg[tg.name]={count=#cands, near=names}; '
    'if #cands==1 then E[tg.name]=cands[1] '
    'elseif #cands>1 then '
    'local best,bd=nil,999; for _,c in pairs(cands) do local d=((c.position.x-tg.x)^2+(c.position.y-tg.y)^2)^0.5; if d<bd then best,bd=c,d end end; '
    'E[tg.name]=best end '
    'end; '
    'local expect=' + names_lua + '; local missing={}; '
    'for _,n in pairs(expect) do if not E[n] then table.insert(missing,n) end end; '
    'if #missing>0 then '
    'helpers.write_file("octave_trace_register_v2.json", helpers.table_to_json({error="entities not found", missing=missing, dbg=dbg}), false); '
    'game.print("MISSING: "..table.concat(missing,",").." - see octave_trace_register_v2.json"); return end; '
    # --- per-tick logger, log on ANY change, single-connector reads only ---
    'local WATCH={ '
    '{key="D", e=E.addr, cid=defines.wire_connector_id.combinator_output_red, sig="signal-D"}, '
    '{key="v_bc", e=E.value_bc, cid=defines.wire_connector_id.combinator_output_red, sig="signal-V"}, '
    '{key="v_r0", e=E.read_0, cid=defines.wire_connector_id.combinator_output_red, sig="signal-V"}, '
    '{key="v_r1", e=E.read_1, cid=defines.wire_connector_id.combinator_output_red, sig="signal-V"}, '
    '{key="v_r2", e=E.read_2, cid=defines.wire_connector_id.combinator_output_red, sig="signal-V"}, '
    '{key="v_r3", e=E.read_3, cid=defines.wire_connector_id.combinator_output_red, sig="signal-V"}, '
    '{key="v_c01", e=E.crelay_0_1, cid=defines.wire_connector_id.combinator_output_red, sig="signal-V"}, '
    '{key="ol", e=E.ol_local, cid=defines.wire_connector_id.combinator_output_green, sig="signal-L"}, '
    '{key="l_r7", e=E.read_7, cid=defines.wire_connector_id.combinator_output_red, sig="signal-L"}, '
    '{key="l_r8", e=E.read_8, cid=defines.wire_connector_id.combinator_output_red, sig="signal-L"}, '
    '{key="l_c11", e=E.crelay_1_1, cid=defines.wire_connector_id.combinator_output_red, sig="signal-L"}, '
    '{key="l_c21", e=E.crelay_2_1, cid=defines.wire_connector_id.combinator_output_red, sig="signal-L"}, '
    '{key="s", e=E.s_e, cid=defines.wire_connector_id.combinator_output_red, sig="signal-S"}, '
    '}; '
    'for _,w in pairs(WATCH) do if not w.e then '
    'helpers.write_file("octave_trace_register_v2.json", helpers.table_to_json({error="WATCH entry has nil e", key=w.key}), false); '
    'game.print("WATCH nil e for "..w.key); return end end; '
    'local log={}; local last={}; '
    'script.on_event(defines.events.on_tick, function(event) '
    'for _,w in pairs(WATCH) do '
    'if w.e.valid then '
    'local ok,sigs=pcall(function() return w.e.get_signals(w.cid) end); '
    'local cur=nil; '
    'if ok and sigs then for _,sg in pairs(sigs) do if sg.signal.name==w.sig then cur=sg.count end end end; '
    'if cur~=last[w.key] then table.insert(log, {tick=event.tick, key=w.key, val=cur}); last[w.key]=cur; '
    'if #log>4000 then table.remove(log,1) end end '
    'end end; '
    'if event.tick % 1000 == 0 then '
    'helpers.write_file("octave_bug_tick_trace.json", helpers.table_to_json({log=log, tick=event.tick}), false) end '
    'end); '
    'helpers.write_file("octave_trace_register_v2.json", helpers.table_to_json({registered=true, dbg=dbg, tick=game.tick}), false); '
    'game.print("tick trace registered at tick "..game.tick)'
)

with open("octave_trace_register_v2_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes")
