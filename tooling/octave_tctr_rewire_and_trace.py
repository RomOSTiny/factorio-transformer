"""
Repair for octave_bug_tick_trace_cmd.txt's crash: it destroyed old t_ctr,
created a fresh one at the same position (correctly parameterized - the
parameters= assignment ran before the crash), but then died reconnecting
the self-loop (t_ctr's own recorded connection had target=old, which by
that point was already destroy()'d - "LuaEntity API call when LuaEntity
was invalid"). octave_tctr_state_check.json confirmed: fresh t_ctr exists,
zero wires, empty output (no network to report onto).

Fix: don't record/replay old connections at all - the required topology is
already known directly from stage2_octave_isolated_test.py's source (t_ctr
self-loop RED output->input, t_ctr->addr RED, t_ctr->tmod RED), so just
wire those 3 connections explicitly. No destroy() involved this time, so
no self-reference-after-destroy risk. Then register the same per-tick
logger octave_bug_tick_trace_cmd.txt would have (same WATCH list), so this
single command finishes the job in one shot.
"""
OX, OY = 94.0, -156.0

UNITS = {
    "read_0": 1345, "read_1": 1351, "read_2": 1357, "read_3": 1361,
    "crelay_0_1": 1360,
    "read_7": 1522, "read_8": 1465,
    "crelay_1_1": 1521, "crelay_2_1": 1524,
}

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
    '/c local surf=game.player.surface; '
    'local U=' + units_lua + '; '
    'local E={}; for k,u in pairs(U) do E[k]=game.get_entity_by_unit_number(u) end; '
    'local fb=' + find_lua + '; '
    'for _,tg in pairs(fb) do '
    'local cands=surf.find_entities_filtered{area={{tg.x-1.3,tg.y-1.3},{tg.x+1.3,tg.y+1.3}}, type="arithmetic-combinator"}; '
    'if #cands==0 then cands=surf.find_entities_filtered{area={{tg.x-1.3,tg.y-1.3},{tg.x+1.3,tg.y+1.3}}, type="decider-combinator"} end; '
    'E[tg.name]=cands[1] end; '
    'local missing={}; for k,v in pairs(E) do if not v then table.insert(missing,k) end end; '
    'if #missing>0 then '
    'helpers.write_file("octave_tctr_rewire.json", helpers.table_to_json({error="entities not found", missing=missing}), false); '
    'game.print("MISSING: "..table.concat(missing,",")); return end; '
    # --- rewire t_ctr directly from known source topology, no record/replay ---
    'local RED=defines.wire_connector_id; '
    'local t_out=E.t_ctr.get_wire_connector(RED.combinator_output_red,true); '
    'local t_in=E.t_ctr.get_wire_connector(RED.combinator_input_red,true); '
    't_out.connect_to(t_in,false,defines.wire_origin.script); '
    'local addr_in=E.addr.get_wire_connector(RED.combinator_input_red,true); '
    't_out.connect_to(addr_in,false,defines.wire_origin.script); '
    'local tmod_in=E.tmod.get_wire_connector(RED.combinator_input_red,true); '
    't_out.connect_to(tmod_in,false,defines.wire_origin.script); '
    # --- confirm wiring before registering the logger ---
    'local check={}; for _,cid in pairs({RED.combinator_input_red, RED.combinator_output_red}) do '
    'local con=E.t_ctr.get_wire_connector(cid,false); if con then for _,c in pairs(con.connections) do '
    'local t=c.target; if t and t.owner and t.owner.valid then table.insert(check, {my_cid=cid, to_unit=t.owner.unit_number, to_x=t.owner.position.x, to_y=t.owner.position.y}) end end end end; '
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
    'helpers.write_file("octave_tctr_rewire.json", helpers.table_to_json({rewired=true, tctr_wires=check, tick=game.tick}), false); '
    'game.print("t_ctr rewired + tick trace registered at tick "..game.tick)'
)

with open("octave_tctr_rewire_and_trace_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes")
