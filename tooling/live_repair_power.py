import sys
sys.path.insert(0, r"C:\Users\roma_\Desktop\factorio-ai\tooling")
from rcon_client import connect

PX, PY = float(sys.argv[1]), float(sys.argv[2])
HX, HY = float(sys.argv[3]), float(sys.argv[4])

lua = f'''
local surf = game.surfaces["nauvis"]
local area = {{{{{PX-HX},{PY-HY}}},{{{PX+HX},{PY+HY}}}}}
local subs = surf.find_entities_filtered{{area=area, name="substation"}}
local poles = surf.find_entities_filtered{{area=area, name="medium-electric-pole"}}
local all={{}}
for _,e in pairs(subs) do all[#all+1]=e end
for _,e in pairs(poles) do all[#all+1]=e end
local G={{}}
local function bk(x,y) return math.floor(x/9)..","..math.floor(y/9) end
for _,e in pairs(all) do local k=bk(e.position.x,e.position.y); G[k]=G[k] or {{}}; table.insert(G[k],e) end
local made=0
for _,e in pairs(all) do
  local reach=(e.name=="substation") and 18 or 9
  local ec=e.get_wire_connector(defines.wire_connector_id.pole_copper,true)
  local bx,by=math.floor(e.position.x/9),math.floor(e.position.y/9)
  local span=math.ceil(reach/9)+1
  for dx=-span,span do for dy=-span,span do
    local l=G[(bx+dx)..","..(by+dy)]
    if l then for _,o in pairs(l) do
      if o~=e and o.valid then
        local dd=math.sqrt((o.position.x-e.position.x)^2+(o.position.y-e.position.y)^2)
        local orr=(o.name=="substation") and 18 or 9
        if dd<=math.min(reach,orr) then
          local present=false
          local ok,cs=pcall(function() return ec.connections end)
          if ok and cs then for _,cn in pairs(cs) do
            if cn.target and cn.target.owner and cn.target.owner.valid and cn.target.owner.unit_number==o.unit_number then present=true break end
          end end
          if not present then
            if pcall(function() ec.connect_to(o.get_wire_connector(defines.wire_connector_id.pole_copper,true),false,defines.wire_origin.script) end) then made=made+1 end
          end
        end
      end
    end end
  end end
end
local nets={{}}
for _,s in pairs(subs) do nets[tostring(s.electric_network_id)]=true end
local nn=0 for _ in pairs(nets) do nn=nn+1 end
rcon.print(helpers.table_to_json({{power_links=made, n_subs=#subs, n_poles=#poles, distinct_nets=nn}}))
'''

with connect(timeout=240) as c:
    print(c.command("/c " + lua.replace("\n", " ")))
