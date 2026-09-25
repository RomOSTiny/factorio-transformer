"""
Two failed attempts narrowed connect_to's real signature empirically:
  - colon + 1 explicit arg (self+target=2 total) -> "bool expected, got
    userdata" (a type error, not a count error - so 2 total args is
    structurally fine, but whatever landed in the checked slot was wrong
    type)
  - colon + 3 explicit args (self+target+false+origin=4 total) ->
    "Arguments count error... Expected between 1 and 3 arguments but 4
    were given" - so max 3 TOTAL (including self), i.e. at most 2
    explicit args via colon syntax.
Putting these together: with only 1 explicit arg (the target connector)
occupying total-position-2, Factorio complained THAT position wanted a
bool - meaning the real signature is very likely
connect_to(no_copy_data: boolean, target: WireConnectorTarget), boolean
FIRST, not connect_to(target, boolean) as originally assumed from the
(apparently outdated or misremembered) reference. This version tries
multiple candidate orderings per connection via pcall, wrapped so a wrong
guess reports a clean error string instead of crashing the whole command,
and uses whichever variant actually succeeds. Does not touch the already-
running v3 tick logger.
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
    'helpers.write_file("octave_tctr_fix_v2.json", helpers.table_to_json({error="not found", missing=missing}), false); '
    'game.print("MISSING: "..table.concat(missing,",")); return end; '
    'local RED=defines.wire_connector_id; '
    'local function try_wire(a,b) '
    'local attempts={}; '
    'local ok1,res1=pcall(function() return a.connect_to(b,false,defines.wire_origin.script) end); '
    'table.insert(attempts,{variant="dot_target_bool_origin", ok=ok1, err=(not ok1) and tostring(res1) or "", ret=tostring(res1)}); '
    'if ok1 and res1 then return true,attempts,"dot_target_bool_origin" end; '
    'local ok2,res2=pcall(function() return a.connect_to(b,false) end); '
    'table.insert(attempts,{variant="dot_target_bool", ok=ok2, err=(not ok2) and tostring(res2) or "", ret=tostring(res2)}); '
    'if ok2 and res2 then return true,attempts,"dot_target_bool" end; '
    'local ok3,res3=pcall(function() return a.connect_to(b) end); '
    'table.insert(attempts,{variant="dot_target_only", ok=ok3, err=(not ok3) and tostring(res3) or "", ret=tostring(res3)}); '
    'if ok3 and res3 then return true,attempts,"dot_target_only" end; '
    'local ok4,res4=pcall(function() return a:connect_to(b,false) end); '
    'table.insert(attempts,{variant="colon_target_bool", ok=ok4, err=(not ok4) and tostring(res4) or "", ret=tostring(res4)}); '
    'return (ok4 and res4)==true,attempts,"colon_target_bool" '
    'end; '
    'local t_out=E.t_ctr.get_wire_connector(RED.combinator_output_red,true); '
    'local t_in=E.t_ctr.get_wire_connector(RED.combinator_input_red,true); '
    'local addr_in=E.addr.get_wire_connector(RED.combinator_input_red,true); '
    'local tmod_in=E.tmod.get_wire_connector(RED.combinator_input_red,true); '
    'local r1ok,r1at,r1v=try_wire(t_out,t_in); '
    'local r2ok,r2at,r2v=try_wire(t_out,addr_in); '
    'local r3ok,r3at,r3v=try_wire(t_out,tmod_in); '
    'local check={}; for _,cid in pairs({RED.combinator_input_red, RED.combinator_output_red}) do '
    'local con=E.t_ctr.get_wire_connector(cid,false); if con then for _,c in pairs(con.connections) do '
    'local t=c.target; if t and t.owner and t.owner.valid then table.insert(check, {my_cid=cid, to_unit=t.owner.unit_number, to_x=t.owner.position.x, to_y=t.owner.position.y}) end end end end; '
    'local ok5,sigs=pcall(function() return E.t_ctr.get_signals(RED.combinator_output_red) end); '
    'local out_red={}; if ok5 and sigs then for _,sg in pairs(sigs) do table.insert(out_red,{name=sg.signal.name,count=sg.count}) end end; '
    'helpers.write_file("octave_tctr_fix_v2.json", helpers.table_to_json({ '
    'selfloop={ok=r1ok, winning_variant=r1v, attempts=r1at}, '
    'addr_link={ok=r2ok, winning_variant=r2v, attempts=r2at}, '
    'tmod_link={ok=r3ok, winning_variant=r3v, attempts=r3at}, '
    'wires_after=check, out_red=out_red, tick=game.tick}), false); '
    'game.print("t_ctr fix v2 attempted, wires now: "..#check)'
)

with open("octave_tctr_fix_v2_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes")
