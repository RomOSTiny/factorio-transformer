"""
Reshenie 25 RESUME POINT continuation: idempotent repair (entities, then
wires) + final out_j check, parameterized by OX,OY - the LOCAL->WORLD
position offset. OX,OY are measured live off t_ctr's real position after
build+revive (see build_clean_pipeline.py's revive_offset_cmd), not computed
analytically from bbox math - build_blueprint's own bounding-box centering
may include entity-footprint corrections that a naive min/max-of-.position
computation would miss, and a systematic offset would silently break every
single position lookup below. Fill in OX, OY from clean_revive.json's
tctr_pos before running this (tctr_pos.x - 0.5, tctr_pos.y - 1.0).

Wire-repair idempotency fix (the actual RESUME POINT bug): the OLD script
called connect_to() unconditionally for every manifest edge, including the
~526 out of 528 that were already fine after revive() - on a second run (or
even within a first run touching an already-correct edge) this creates a
SECOND parallel wire on top of a working one (observed as in_red=2,
in_green=2, garbage signal values). Fix here: for every (position,connector)
key, precompute how many manifest edges touch it (`expected`), then before
connect_to on any specific edge, check BOTH endpoints' LuaWireConnector.
real_connection_count against that expected count - only connect if at
least one side is still short. This works correctly even for legitimate
multi-connection ports (e.g. acc_j's output feeds both itself and out_j)
because `expected` is a per-port total, not a per-edge flag.
"""
import math

OX, OY = -1577.0, -1710.0  # measured live: tctr_pos (-1576.5,-1709) - local (0.5,1.0)
assert OX is not None and OY is not None, "set OX, OY from clean_revive.json tctr_pos first"

BX, BY = -1500, -1500
AX1, AY1, AX2, AY2 = BX - 280, BY - 250, BX + 280, BY + 250
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

with open("repair_entities.lua_data") as f:
    entities_data = f.read().strip()
with open("repair_wires.lua_data") as f:
    wires_data = f.read().strip()

repair_entities_cmd = (
    '/c local surf=game.player.surface; local OX,OY=' + repr(OX) + ',' + repr(OY) + '; '
    'local D=' + entities_data + '; '
    'local created,already,failed=0,0,0; '
    'for i=1,#D do local d=D[i]; local wx,wy=d[2]+OX,d[3]+OY; '
    'local found=surf.find_entities_filtered{type="arithmetic-combinator", area={{wx-0.4,wy-0.4},{wx+0.4,wy+0.4}}}; '
    'if #found==0 then '
    'local ok,e=pcall(function() return surf.create_entity{name="arithmetic-combinator", position={wx,wy}, force=game.player.force} end); '
    'if ok and e and e.valid then '
    'local cb=e.get_or_create_control_behavior(); '
    'local ok2=pcall(function() cb.parameters={first_signal={type="virtual",name=d[4]}, operation=d[5], '
    'second_signal=(d[6] and {type="virtual",name=d[6]} or nil), second_constant=(d[6] and nil or d[7]), '
    'output_signal={type="virtual",name=d[8]}} end); '
    'if ok2 then created=created+1 else failed=failed+1 end '
    'else failed=failed+1 end '
    'else already=already+1 end end; '
    'helpers.write_file("matmul_repair_entities_result.json", helpers.table_to_json({created=created,already=already,failed=failed}), false)'
)
with open("matmul_repair_entities_cmd.txt", "w") as f:
    f.write(repair_entities_cmd)

repair_wires_cmd = (
    '/c local surf=game.player.surface; local OX,OY=' + repr(OX) + ',' + repr(OY) + '; '
    'local W=' + wires_data + '; '
    'local function key(x,y,c) return string.format("%.2f,%.2f,%d", x, y, c) end; '
    'local expected={}; '
    'for i=1,#W do local w=W[i]; '
    'local k1=key(w[1]+OX,w[2]+OY,w[3]); local k2=key(w[4]+OX,w[5]+OY,w[6]); '
    'expected[k1]=(expected[k1] or 0)+1; expected[k2]=(expected[k2] or 0)+1; end; '
    'local buckets={}; '
    'for _,e in pairs(surf.find_entities_filtered{type={"arithmetic-combinator","decider-combinator"}, area=' + area + '}) do '
    'local bk=math.floor(e.position.x)..","..math.floor(e.position.y); '
    'buckets[bk]=buckets[bk] or {}; table.insert(buckets[bk], e) end; '
    'local function find_near(x,y) '
    'local bx,by=math.floor(x),math.floor(y); '
    'for dx=-1,1 do for dy=-1,1 do '
    'local list=buckets[(bx+dx)..","..(by+dy)]; '
    'if list then for _,e in pairs(list) do '
    'if math.abs(e.position.x-x)<0.6 and math.abs(e.position.y-y)<0.6 then return e end '
    'end end end end return nil end; '
    'local function has_edge(con1, target_unit, target_cid) '
    'local ok,conns=pcall(function() return con1.connections end); '
    'if not ok or not conns then return nil end; '
    'for _,conn in pairs(conns) do '
    'local t=conn.target; '
    'if t and t.owner and t.owner.valid and t.owner.unit_number==target_unit and t.wire_connector_id==target_cid then return true end '
    'end return false end; '
    'local connected,already,missing,failed,fallback_used=0,0,0,0,0; '
    'for i=1,#W do local w=W[i]; '
    'local x1,y1,c1=w[1]+OX,w[2]+OY,w[3]; local x2,y2,c2=w[4]+OX,w[5]+OY,w[6]; '
    'local e1=find_near(x1,y1); local e2=find_near(x2,y2); '
    'if e1==nil or e2==nil then missing=missing+1 else '
    'local ok=pcall(function() '
    'local con1=e1.get_wire_connector(c1,true); local con2=e2.get_wire_connector(c2,true); '
    'local exists=has_edge(con1, e2.unit_number, c2); '
    'if exists==nil then fallback_used=fallback_used+1; '
    'local exp1=expected[key(x1,y1,c1)] or 1; local exp2=expected[key(x2,y2,c2)] or 1; '
    'if con1.real_connection_count<exp1 or con2.real_connection_count<exp2 then '
    'con1.connect_to(con2,false,defines.wire_origin.script); connected=connected+1 '
    'else already=already+1 end '
    'elseif exists then already=already+1 '
    'else con1.connect_to(con2,false,defines.wire_origin.script); connected=connected+1 end end); '
    'if not ok then failed=failed+1 end end end; '
    'helpers.write_file("matmul_repair_wires_result.json", helpers.table_to_json({connected=connected,already=already,missing=missing,failed=failed,fallback_used=fallback_used}), false)'
)
with open("matmul_repair_wires_cmd.txt", "w") as f:
    f.write(repair_wires_cmd)

# final check: dump the accumulator row (acc_j + out_j interleaved on the
# same y, distinguished downstream in Python by operation: "/" = out_j)
ROW_X1, ROW_X2 = 149.5 + OX, 243.5 + OX
ROW_Y1, ROW_Y2 = 419.5 + OY, 422.5 + OY
row_area = "{{" + str(ROW_X1) + "," + str(ROW_Y1) + "},{" + str(ROW_X2) + "," + str(ROW_Y2) + "}}"
final_check_cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", area=' + row_area + '}) do '
    'local cb=e.get_control_behavior(); local op=(cb and cb.parameters and cb.parameters.operation) or "?"; '
    'local ok,sig=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local val=0; if ok and sig then for _,s in pairs(sig) do if s.signal.name=="signal-A" then val=s.count end end end; '
    'out[#out+1]={x=e.position.x, op=op, val=val} end; '
    'helpers.write_file("matmul_final_check.json", helpers.table_to_json(out), false)'
)
with open("matmul_final_check_cmd.txt", "w") as f:
    f.write(final_check_cmd)

print("repair_entities_cmd bytes:", len(repair_entities_cmd))
print("repair_wires_cmd bytes:", len(repair_wires_cmd))
print("final_check_cmd bytes:", len(final_check_cmd))
print("row_area:", row_area)
