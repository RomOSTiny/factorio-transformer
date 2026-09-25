BX, BY = 500, -3000
area = "{{" + str(BX - 280) + "," + str(BY - 250) + "},{" + str(BX + 280) + "," + str(BY + 250) + "}}"
cmd = (
    '/c local surf=game.player.surface; '
    'surf.request_to_generate_chunks({x=' + str(BX) + ',y=' + str(BY) + '}, 15); '
    'surf.force_generate_chunk_requests(); '
    'local gen=surf.is_chunk_generated({x=' + str(BX // 32) + ',y=' + str(BY // 32) + '}); '
    'local counts={}; for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do counts[e.type]=(counts[e.type] or 0)+1 end; '
    'local water=0; for x=-5,5 do for y=-5,5 do local t=surf.get_tile(' + str(BX) + '+x,' + str(BY) + '+y); if t and not t.valid then water=water+1 end end end; '
    'helpers.write_file("recon2.json", helpers.table_to_json({chunk_generated=gen, counts=counts, tick=game.tick}), false)'
)
with open("recon2_cmd.txt", "w") as f:
    f.write(cmd)
print(len(cmd))
