"""
v2 diagnosed itself correctly (explicit missing-check this time, no more
silent nil): ALL 9 unit_number-based lookups (read_0/1/2/3, crelay_0_1,
read_7, read_8, crelay_1_1, crelay_2_1) came back nil from
game.get_entity_by_unit_number, while every position-based lookup
(addr, value_bc, ol_local, s_e) succeeded fine, including at the exact
same live coordinates recorded for those same 9 entities in this
session's own first query (octave_col_transition_check.json) - e.g. unit
1465 was confirmed live at (353.5,-5) as olrom_read_8 in that query, yet
get_entity_by_unit_number(1465) now returns nil. Why unit_number lookup
stopped working for exactly this set is unresolved (not a coordinate
mistake - the positions matched). Rather than debug that mystery further,
this version drops unit_number entirely and re-finds all 9 by position
(same technique already proven reliable for addr/value_bc/ol_local/s_e in
v2, and originally for all of these in octave_col_transition_check.json),
using each entity's exact local blueprint coordinate + a type filter
(decider-combinator for read_i, arithmetic-combinator for crelay) to
disambiguate from the neighbor 1 tile away that a 1.3-tile radius also
catches (vrelay/crelay sit right next to their read).
"""
OX, OY = 94.0, -156.0

# (label, local_x, local_y, type, radius)
FIND_BY_POS = [
    ("addr", 0.5, 4.0, "arithmetic-combinator", 1.3),
    ("value_bc", 230.5, -10.0, "arithmetic-combinator", 4.0),
    ("ol_local", 245.5, 301.0, "arithmetic-combinator", 4.0),
    ("s_e", 250.5, 304.0, "arithmetic-combinator", 4.0),
    ("read_0", 2.5, 101.0, "decider-combinator", 1.3),
    ("read_1", 2.5, 103.0, "decider-combinator", 1.3),
    ("read_2", 2.5, 105.0, "decider-combinator", 1.3),
    ("read_3", 2.5, 107.0, "decider-combinator", 1.3),
    ("crelay_0_1", 3.5, 107.0, "arithmetic-combinator", 1.3),
    ("read_7", 256.5, 157.0, "decider-combinator", 1.3),
    ("read_8", 260.5, 151.0, "decider-combinator", 1.3),
    ("crelay_1_1", 257.5, 157.0, "arithmetic-combinator", 1.3),
    ("crelay_2_1", 261.5, 157.0, "arithmetic-combinator", 1.3),
]

ALL_NAMES = [n for n, *_ in FIND_BY_POS]
find_lua = "{" + ",".join(
    f'{{name="{n}",x={x + OX},y={y + OY},r={r},ty="{ty}"}}' for n, x, y, ty, r in FIND_BY_POS
) + "}"
names_lua = "{" + ",".join(f'"{n}"' for n in ALL_NAMES) + "}"

cmd = (
    '/c local surf=game.player.surface; '
    'local E={}; local fb=' + find_lua + '; local dbg={}; '
    'for _,tg in pairs(fb) do '
    'local cands=surf.find_entities_filtered{area={{tg.x-tg.r,tg.y-tg.r},{tg.x+tg.r,tg.y+tg.r}}, type=tg.ty}; '
    'local names={}; for _,c in pairs(cands) do table.insert(names, {x=c.position.x,y=c.position.y,unit=c.unit_number}) end; '
    'dbg[tg.name]={count=#cands, near=names}; '
    'local best,bd=nil,999; for _,c in pairs(cands) do local d=((c.position.x-tg.x)^2+(c.position.y-tg.y)^2)^0.5; if d<bd then best,bd=c,d end end; '
    'E[tg.name]=best '
    'end; '
    'local expect=' + names_lua + '; local missing={}; '
    'for _,n in pairs(expect) do if not E[n] then table.insert(missing,n) end end; '
    'if #missing>0 then '
    'helpers.write_file("octave_trace_register_v3.json", helpers.table_to_json({error="entities not found", missing=missing, dbg=dbg}), false); '
    'game.print("MISSING: "..table.concat(missing,",").." - see octave_trace_register_v3.json"); return end; '
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
    'helpers.write_file("octave_trace_register_v3.json", helpers.table_to_json({error="WATCH entry has nil e", key=w.key}), false); '
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
    'helpers.write_file("octave_trace_register_v3.json", helpers.table_to_json({registered=true, dbg=dbg, tick=game.tick}), false); '
    'game.print("tick trace registered at tick "..game.tick)'
)

with open("octave_trace_register_v3_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes")
