"""
Live (in-game) check for Reshenie 32's column-transition hypothesis. Static
blueprint check (octave_hrelay_trace.py) already proved the BLUEPRINT's own
wiring around vrom's hrelay_0/hrelay_1 (address 0's own column) and olrom's
hrelay_1/hrelay_2 + col_collectors[1]->col_collectors[2] (o=8's column) is
100% correct - so if there's a real bug there, it can only be a LIVE
placement/revive/repair-time artifact, not a Python source bug.

Prime suspect: build_addressed_rom's `hrelay` entities are the only
position= entities in stage2_octave_isolated_test.py with an INTEGER local
X/Y (every other position= call in that file was retroactively patched with
a non-integer offset after this session found integer-local-X entities get
a +0.5 shift at live placement while tile_position= entities - which always
land on a .5 grid once exported - do not). If that shift causes a manifest
mismatch during repair, a duplicate/orphaned hrelay could exist alongside
the real one, or the real one could have silently lost specific wires
(Reshenie 27's class-7 bug) without the entity itself vanishing.

This script finds t_ctr live to (re)confirm OX,OY (never trust the
analytically-carried-over offset without re-measuring - Reshenie 29's
rule), then for each target entity below: searches a generous radius (to
catch BOTH the intended spot and any nearby duplicate/shifted twin),
reports every combinator found there (type, exact position, unit_number),
and dumps that entity's live wire connections on all 4 connector ports.
"""
import json

# (label, local_x, local_y) - local center positions taken directly from
# the actual built blueprint (stage2_octave_isolated_test_blueprint.txt),
# via octave_hrelay_trace.py's parse - not hand-computed, so no risk of
# repeating that script's earlier tile/center arithmetic mistake.
TARGETS = [
    ("vrom_hrelay_0", 0.0, 90.0),
    ("vrom_hrelay_1", 4.0, 90.0),
    ("vrom_vrelay_0_0", 1.5, 93.0),
    ("vrom_vrelay_0_1", 1.5, 101.0),
    ("vrom_vrelay_1_0", 5.5, 93.0),
    ("vrom_crelay_0_0", 3.5, 115.0),
    ("vrom_crelay_0_1", 3.5, 107.0),
    ("vrom_store_0", 0.5, 100.5),
    ("vrom_read_0", 2.5, 101.0),
    ("vrom_store_3", 0.5, 106.5),
    ("vrom_read_3", 2.5, 107.0),
    ("olrom_hrelay_1", 254.0, 140.0),
    ("olrom_hrelay_2", 258.0, 140.0),
    ("olrom_vrelay_2_0", 259.5, 143.0),
    ("olrom_vrelay_2_1", 259.5, 151.0),
    ("olrom_crelay_1_0", 257.5, 165.0),
    ("olrom_crelay_1_1", 257.5, 157.0),
    ("olrom_crelay_2_0", 261.5, 165.0),
    ("olrom_crelay_2_1", 261.5, 157.0),
    ("olrom_store_7", 254.5, 156.5),
    ("olrom_read_7", 256.5, 157.0),
    ("olrom_store_8", 258.5, 150.5),
    ("olrom_read_8", 260.5, 151.0),
]

# fallback OX,OY guess to center the t_ctr search box on - per CONTINUE_HERE.md
# (Reshenie 32), re-measured, not trusted blindly (search radius covers a
# generous margin in case it drifted or this is actually a different world).
GUESS_OX, GUESS_OY = 94.0, -156.0
TCTR_LOCAL_X, TCTR_LOCAL_Y = 0.5, 1.0
SEARCH_R = 60

lua_targets = "{" + ",".join(
    f'{{name="{name}",x={x},y={y}}}' for name, x, y in TARGETS
) + "}"

gx = GUESS_OX + TCTR_LOCAL_X
gy = GUESS_OY + TCTR_LOCAL_Y

cmd = (
    '/c local surf=game.player.surface; '
    f'local gx,gy={gx},{gy}; local R={SEARCH_R}; '
    'local tctr=nil; '
    'for _,e in pairs(surf.find_entities_filtered{type="arithmetic-combinator", '
    'area={{gx-R,gy-R},{gx+R,gy+R}}}) do '
    'local ok,sig=pcall(function() return e.get_signals(defines.wire_connector_id.combinator_output_red, '
    'defines.wire_connector_id.combinator_output_green) end); '
    'if ok and sig then for _,s in pairs(sig) do if s.signal.name=="signal-T" then tctr=e end end end end; '
    'if not tctr then '
    'helpers.write_file("octave_col_transition_check.json", helpers.table_to_json({error="t_ctr not found within radius, world may differ from CONTINUE_HERE.md offset"}), false); '
    'game.print("t_ctr NOT FOUND - see octave_col_transition_check.json"); return end; '
    f'local OX,OY=tctr.position.x-{TCTR_LOCAL_X},tctr.position.y-{TCTR_LOCAL_Y}; '
    'local out={}; local targets=' + lua_targets + '; '
    'local function dump_wires(e) local w={}; '
    'for _,cid in pairs({defines.wire_connector_id.combinator_input_red, defines.wire_connector_id.combinator_input_green, '
    'defines.wire_connector_id.combinator_output_red, defines.wire_connector_id.combinator_output_green}) do '
    'local ok,con=pcall(function() return e.get_wire_connector(cid,false) end); '
    'if ok and con then local ok2,cs=pcall(function() return con.connections end); '
    'if ok2 and cs then for _,c in pairs(cs) do local t=c.target; if t and t.owner and t.owner.valid then '
    'table.insert(w, {my_cid=cid, to_unit=t.owner.unit_number, to_cid=t.wire_connector_id, to_name=t.owner.name, to_x=t.owner.position.x, to_y=t.owner.position.y}) '
    'end end end end end return w end; '
    'for _,tg in pairs(targets) do '
    'local wx,wy=tg.x+OX,tg.y+OY; '
    'local hits={}; '
    'for _,e in pairs(surf.find_entities_filtered{area={{wx-1.3,wy-1.3},{wx+1.3,wy+1.3}}}) do '
    'if e.type=="arithmetic-combinator" or e.type=="decider-combinator" or e.type=="constant-combinator" then '
    'table.insert(hits, {type=e.type, name=e.name, unit=e.unit_number, x=e.position.x, y=e.position.y, '
    'dx=e.position.x-wx, dy=e.position.y-wy, wires=dump_wires(e)}) '
    'end end '
    'out[#out+1]={target=tg.name, expected_x=wx, expected_y=wy, hits=hits} '
    'end; '
    'helpers.write_file("octave_col_transition_check.json", helpers.table_to_json({tctr_pos={x=tctr.position.x,y=tctr.position.y}, OX=OX, OY=OY, out=out}), false); '
    'game.print("col transition live check written, OX="..OX.." OY="..OY)'
)

with open("octave_col_transition_check_cmd.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(len(cmd), "bytes written to octave_col_transition_check_cmd.txt")
