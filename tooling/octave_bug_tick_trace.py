"""
Reshenie 32's two open bugs (address 0 reading address 3's value ROM data;
subbucket s stuck at 32 on address 2) survive a full live wire-connectivity
audit (octave_col_transition_live_check.py): every wire around hrelay_0/1,
vrelay/crelay chains, and the col_collectors junction is present and
correctly targeted, both in the blueprint AND live in-game (hrelay's known
+0.5 live position shift is confirmed real but does NOT drop or misroute
any wire). So this is not a wiring/topology defect - it must be a genuine
timing/logic effect only visible tick-by-tick, same class of thing that
resolved matmul's signal-P glitch (Reshenie 26) and this file's own
diff_e/half_e/s_e mystery (Reshenie 32, "Utochnenie nakhodki 2").

This resets t_ctr (destroy + recreate at the same position, reconnect its
exact previous wire connections via the project's proven
wireConnector.connect_to(other, false, defines.wire_origin.script) API -
Reshenie 9) - required because it's been running unattended since the last
session and signal-D has long since swept past every valid address - and
registers a per-tick logger on the RAW per-row read outputs (not just the
aggregated/collector values Reshenie 32 already checked), so if the
corruption is a genuine transient at a specific tick, this catches it, not
just the settled-but-wrong aftermath. Every signal is read on its OWN
single wire-connector only (get_signals(one cid), Reshenie 31's rule) -
value_bc/read_i(V)/crelay(V)/s_e are all RED-only, ol_local/vrelay are
GREEN-only, per build_addressed_rom's own wiring (checked directly against
the source).

Unit numbers for read_0/1/2/3, crelay_0_1, read_7, read_8, crelay_1_1,
crelay_2_1 are taken directly from octave_col_transition_check.json (this
session's own live query), not recomputed - avoids repeating any position-
math mistake. t_ctr/addr/tmod/value_bc/ol_local/s_e are found fresh by
position in this same command since that query didn't target them.
"""
OX, OY = 94.0, -156.0

# from octave_col_transition_check.json (already confirmed live, this session)
UNITS = {
    "read_0": 1345, "read_1": 1351, "read_2": 1357, "read_3": 1361,
    "crelay_0_1": 1360,
    "read_7": 1522, "read_8": 1465,
    "crelay_1_1": 1521, "crelay_2_1": 1524,
}

# (label, local_x, local_y) for entities not yet identified live
FIND_BY_POS = [
    ("t_ctr", 0.5, 1.0),
    ("addr", 0.5, 4.0),
    ("tmod", 3.5, 1.0),
    ("value_bc", 230.5, -10.0),
    ("ol_local", 245.5, 301.0),
    ("s_e", 250.5, 304.0),
]

units_lua = "{" + ",".join(f'{k}={v}' for k, v in UNITS.items()) + "}"
find_lua = "{" + ",".join(f'{{name="{n}",x={x + OX},y={y + OY}}}' for n, x, y in FIND_BY_POS) + "}"

cmd = (
    '/c local surf=game.player.surface; local force=game.player.force; '
    'local U=' + units_lua + '; '
    'local E={}; for k,u in pairs(U) do E[k]=game.get_entity_by_unit_number(u) end; '
    'local fb=' + find_lua + '; '
    'for _,tg in pairs(fb) do '
    'local cands=surf.find_entities_filtered{area={{tg.x-1.3,tg.y-1.3},{tg.x+1.3,tg.y+1.3}}, type="arithmetic-combinator"}; '
    'if #cands==0 then cands=surf.find_entities_filtered{area={{tg.x-1.3,tg.y-1.3},{tg.x+1.3,tg.y+1.3}}, type="decider-combinator"} end; '
    'E[tg.name]=cands[1] end; '
    'local missing={}; for k,v in pairs(E) do if not v then table.insert(missing,k) end end; '
    'if #missing>0 then '
    'helpers.write_file("octave_bug_tick_trace.json", helpers.table_to_json({error="entities not found", missing=missing}), false); '
    'game.print("MISSING: "..table.concat(missing,",")); return end; '
    # --- reset t_ctr: record its wires, destroy, recreate, rewire ---
    'local old=E.t_ctr; local oldpos={x=old.position.x,y=old.position.y}; '
    'local saved={}; '
    'for _,cid in pairs({defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_output_red}) do '
    'local con=old.get_wire_connector(cid,false); '
    'if con then for _,c in pairs(con.connections) do '
    'local t=c.target; if t and t.owner and t.owner.valid then table.insert(saved, {my_cid=cid, other=t.owner, other_cid=t.wire_connector_id}) end '
    'end end end; '
    'old.destroy(); '
    'local fresh=surf.create_entity{name="arithmetic-combinator", position=oldpos, force=force, raise_built=false}; '
    'fresh.get_or_create_control_behavior().parameters={first_signal={name="signal-T",type="virtual"}, operation="+", second_constant=1, output_signal={name="signal-T",type="virtual"}}; '
    'for _,s in pairs(saved) do '
    'local mycon=fresh.get_wire_connector(s.my_cid,true); '
    'local ocon=s.other.get_wire_connector(s.other_cid,true); '
    'mycon.connect_to(ocon,false,defines.wire_origin.script) '
    'end; '
    'E.t_ctr=fresh; '
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
    'helpers.write_file("octave_bug_tick_trace.json", helpers.table_to_json({log={}, tick=game.tick, reset_ok=true}), false); '
    'game.print("t_ctr reset + tick trace registered at tick "..game.tick)'
)

with open("octave_bug_tick_trace_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes")
