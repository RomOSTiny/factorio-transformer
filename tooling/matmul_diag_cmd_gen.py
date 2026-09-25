BX, BY = 600, 600
AX1, AY1, AX2, AY2 = BX - 50, BY - 50, BX + 50, BY + 50
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

# reuse the EXACT proven per-type connector selection from dump_signals_command.txt (Reshenie 5)
diag_cmd = (
    '/c local out={}; '
    'local ents=game.player.surface.find_entities_filtered{type={"constant-combinator","arithmetic-combinator","decider-combinator"}, area=' + area + '}; '
    'for _,e in pairs(ents) do '
    'local rec={type=e.type,x=e.position.x,y=e.position.y,unit_number=e.unit_number}; '
    'local function dump(label,wr,wg) local ok,signals=pcall(function() return e.get_signals(wr,wg) end); local sp={}; if ok and signals then for _,s in pairs(signals) do sp[#sp+1]={name=s.signal.name,count=s.count} end end; rec[label]=sp end; '
    'if e.type=="constant-combinator" then dump("circuit",defines.wire_connector_id.circuit_red,defines.wire_connector_id.circuit_green) '
    'else dump("output",defines.wire_connector_id.combinator_output_red,defines.wire_connector_id.combinator_output_green) end; '
    'out[#out+1]=rec end; '
    'helpers.write_file("matmul_diag2.json", helpers.table_to_json(out), false)'
)
with open("matmul_diag_cmd.txt", "w") as f:
    f.write(diag_cmd)
print("written")
