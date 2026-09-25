BX, BY = 600, 600
AX1, AY1, AX2, AY2 = BX - 5, BY - 5, BX + 5, BY + 5
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

cmd = (
    '/c local out={}; '
    'for _,e in pairs(game.player.surface.find_entities_filtered{area=' + area + '}) do '
    'out[#out+1]={name=e.name,type=e.type,x=e.position.x,y=e.position.y} end; '
    'helpers.write_file("area_check.json", helpers.table_to_json(out), false)'
)
with open("check_area_cmd.txt", "w") as f:
    f.write(cmd)
print("written")
