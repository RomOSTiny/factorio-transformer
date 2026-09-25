"""
Real fix: octave_tctr_rewire_and_trace.py's connect_to calls used dot
syntax (mycon.connect_to(ocon, false, defines.wire_origin.script)), which
in Lua does NOT pass mycon as the implicit self/receiver - the C-side
connect_to method never actually got the connector it's supposed to
connect FROM, so it silently no-op'd (no Lua error, since Factorio's API
binding apparently just fails the type check on its 3-arg call quietly
rather than throwing). Confirmed by octave_tctr_verify.json: t_ctr still
shows wires={} after that command claimed success. The project's own
proven-working repair code (build_targeted_repair.py) uses COLON syntax
with a single argument: wc1:connect_to(wc2) - matching that exactly here.

Does NOT touch the already-running v3 tick logger (octave_trace_register_v3
registered fine and should pick up real data automatically once T starts
counting) - just fixes t_ctr's 3 wires, then reads them back in the same
command to confirm before ending.
"""
OX, OY = 94.0, -156.0

FIND_BY_POS = [
    ("t_ctr", 0.5, 1.0),
    ("addr", 0.5, 4.0),
    ("tmod", 3.5, 1.0),
]
find_lua = "{" + ",".join(f'{{name="{n}",x={x + OX},y={y + OY}}}' for n, x, y in FIND_BY_POS) + "}"

cmd = (
    '/c local surf=game.player.surface; '
    'local E={}; local fb=' + find_lua + '; '
    'for _,tg in pairs(fb) do '
    'local c=surf.find_entities_filtered{area={{tg.x-1.3,tg.y-1.3},{tg.x+1.3,tg.y+1.3}}, type="arithmetic-combinator"}[1]; '
    'E[tg.name]=c end; '
    'local missing={}; for _,n in pairs({"t_ctr","addr","tmod"}) do if not E[n] then table.insert(missing,n) end end; '
    'if #missing>0 then '
    'helpers.write_file("octave_tctr_fix_colon.json", helpers.table_to_json({error="not found", missing=missing}), false); '
    'game.print("MISSING: "..table.concat(missing,",")); return end; '
    'local RED=defines.wire_connector_id; '
    'local t_out=E.t_ctr.get_wire_connector(RED.combinator_output_red,true); '
    'local t_in=E.t_ctr.get_wire_connector(RED.combinator_input_red,true); '
    'local ok1=t_out:connect_to(t_in,false,defines.wire_origin.script); '
    'local addr_in=E.addr.get_wire_connector(RED.combinator_input_red,true); '
    'local ok2=t_out:connect_to(addr_in,false,defines.wire_origin.script); '
    'local tmod_in=E.tmod.get_wire_connector(RED.combinator_input_red,true); '
    'local ok3=t_out:connect_to(tmod_in,false,defines.wire_origin.script); '
    'local check={}; for _,cid in pairs({RED.combinator_input_red, RED.combinator_output_red}) do '
    'local con=E.t_ctr.get_wire_connector(cid,false); if con then for _,c in pairs(con.connections) do '
    'local t=c.target; if t and t.owner and t.owner.valid then table.insert(check, {my_cid=cid, to_unit=t.owner.unit_number, to_x=t.owner.position.x, to_y=t.owner.position.y}) end end end end; '
    'local ok4,sigs=pcall(function() return E.t_ctr.get_signals(RED.combinator_output_red) end); '
    'local out_red={}; if ok4 and sigs then for _,sg in pairs(sigs) do table.insert(out_red,{name=sg.signal.name,count=sg.count}) end end; '
    'helpers.write_file("octave_tctr_fix_colon.json", helpers.table_to_json({connect_results={not not ok1, not not ok2, not not ok3}, wires_after=check, out_red=out_red, tick=game.tick}), false); '
    'game.print("t_ctr fix attempted, wires now: "..#check)'
)

with open("octave_tctr_fix_colon_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes")
