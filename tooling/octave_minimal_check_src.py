cmd = (
    '/c local surf=game.player.surface; local out={}; '
    'local e=surf.find_entities_filtered{type="constant-combinator", area={{494.0,496.0},{495.0,497.0}}}[1]; '
    'if e then '
    'local cb=e.get_control_behavior(); '
    'out.has_cb = cb~=nil; '
    'if cb then '
    'local ok,sections=pcall(function() return cb.sections end); '
    'out.sections_ok=ok; '
    'if ok and sections then '
    'out.section_count=sections.count; '
    'local sec1=sections[1]; '
    'if sec1 then '
    'local ok2,filters=pcall(function() return sec1.filters end); '
    'out.filters_ok=ok2; '
    'out.filters={}; '
    'if ok2 and filters then for _,f in pairs(filters) do table.insert(out.filters,{name=(f.value and f.value.name) or f.name, count=f.count, min=f.min}) end end '
    'end end end '
    'out.enabled=e.get_control_behavior() and true or false; '
    'else out.found=false end; '
    'helpers.write_file("octave_minimal_src.json", helpers.table_to_json(out), false)'
)
with open("octave_minimal_check_src_cmd.txt", "w") as f:
    f.write(cmd)
print(cmd)
