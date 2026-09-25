BX, BY = 900, 900
AX1, AY1, AX2, AY2 = BX - 300, BY - 300, BX + 300, BY + 300
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

cmd = (
    '/c local out={}; '
    'for _,e in pairs(game.player.surface.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}) do '
    'local ok,sig=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green) end); '
    'local sp={}; if ok and sig then for _,s in pairs(sig) do sp[#sp+1]={name=s.signal.name,count=s.count} end end; '
    'if #sp>0 and (sp[1].name=="signal-T" or sp[1].name=="signal-N") then out[#out+1]={x=e.position.x,y=e.position.y,output=sp} end end; '
    'local total=#game.player.surface.find_entities_filtered{type="arithmetic-combinator", area=' + area + '}; '
    'helpers.write_file("tctr2_check.json", helpers.table_to_json({t_or_addr_found=out, total_arith=total}), false)'
)
with open("check_tctr2_cmd.txt", "w") as f:
    f.write(cmd)
print("written")
