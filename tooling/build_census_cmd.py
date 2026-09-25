BX, BY = 500, 500
AX1, AY1, AX2, AY2 = BX - 280, BY - 250, BX + 280, BY + 250
area = "{{" + str(AX1) + "," + str(AY1) + "},{" + str(AX2) + "," + str(AY2) + "}}"

cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'for _,e in pairs(surf.find_entities_filtered{type={"arithmetic-combinator","decider-combinator"}, area=' + area + '}) do '
    'out[#out+1]={x=e.position.x, y=e.position.y, t=e.type} end; '
    'helpers.write_file("matmul_census.json", helpers.table_to_json(out), false)'
)
with open("matmul_census_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd), "bytes")
print("area:", area)
