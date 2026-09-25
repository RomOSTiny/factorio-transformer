import sys, time
sys.path.insert(0, r"C:\Users\roma_\Desktop\factorio-ai\tooling")
import rcon_client

x, y = float(sys.argv[1]), float(sys.argv[2])
threshold = int(sys.argv[3]) if len(sys.argv) > 3 else 2450
lua = f'''
local s = game.surfaces["nauvis"]
local f = s.find_entities_filtered{{area={{{{{x-1.5},{y-1.5}}},{{{x+1.5},{y+1.5}}}}}, type="arithmetic-combinator", limit=1}}
local sig = f[1].get_signals(defines.wire_connector_id.combinator_output_red)
local v = 0
if sig then for _,s2 in pairs(sig) do if s2.signal.name == "signal-T" then v = s2.count end end end
rcon.print(tostring(v))
'''

for i in range(60):
    try:
        c = rcon_client.connect(timeout=10)
        resp = c.command('/c ' + lua.replace("\n", " "))
        c.close()
        val = int(resp.strip() or "0")
        print(f"tctr2={val}")
        if val >= threshold:
            print("DONE: sweep past threshold")
            break
    except Exception as e:
        print("poll error:", e)
    time.sleep(2.0)
else:
    print("TIMEOUT")
