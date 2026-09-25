"""
Recon before the FIRST build attempt at a new map location - mandatory per
Reshenie 26 (biter spawners give entities_built=0 with no warning; recon
catches this cheaply before wasting a build attempt). New spot chosen well
clear of the matmul block's build area (-1500,-1500, +-280/+-250) and every
earlier test build in this project.
"""
BX, BY = 350, 0
area = "{{" + str(BX - 250) + "," + str(BY - 260) + "},{" + str(BX + 250) + "," + str(BY + 260) + "}}"
cmd = (
    '/c local surf=game.player.surface; '
    'surf.request_to_generate_chunks({x=' + str(BX) + ',y=' + str(BY) + '}, 15); '
    'surf.force_generate_chunk_requests(); '
    'local gen=surf.is_chunk_generated({x=' + str(BX // 32) + ',y=' + str(BY // 32) + '}); '
    'local counts={}; for _,e in pairs(surf.find_entities_filtered{area=' + area + '}) do counts[e.type]=(counts[e.type] or 0)+1 end; '
    'helpers.write_file("octave_recon.json", helpers.table_to_json({chunk_generated=gen, counts=counts, tick=game.tick}), false)'
)
with open("octave_recon_cmd.txt", "w") as f:
    f.write(cmd)
print("bytes:", len(cmd))
print(f"BX,BY={BX},{BY}")
