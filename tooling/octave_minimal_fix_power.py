"""o_collect (local x=15.5) sits too far from the power poles (local x=6) -
add one more pole near it. World offset for this build (500,600) matches
relay_0 at world(497.5,597)=local(3.5,1), so offset=(494,596)."""
cmd = (
    '/c local surf=game.player.surface; '
    'local p=surf.create_entity{name="medium-electric-pole", position={509.5,599.5}, force=game.player.force, quality="legendary"}; '
    'helpers.write_file("octave_minimal_fix_power.json", helpers.table_to_json({created=p~=nil and p.valid}), false)'
)
with open("octave_minimal_fix_power_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
