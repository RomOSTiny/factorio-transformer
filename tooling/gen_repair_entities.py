import base64, zlib, json

with open("stage2_matmul_test_blueprint.txt") as f:
    s = f.read().strip()
raw = base64.b64decode(s[1:])
data = json.loads(zlib.decompress(raw))
bp = data["blueprint"]
entities = bp["entities"]

relevant_types = {"arithmetic-combinator", "decider-combinator"}
lines = []
for e in entities:
    if e["name"] not in relevant_types:
        continue
    p = e["position"]
    if e["name"] == "arithmetic-combinator":
        ac = e.get("control_behavior", {}).get("arithmetic_conditions", {})
        fs = ac.get("first_signal", {}).get("name", "")
        op = ac.get("operation", "*")
        sc = ac.get("second_signal")
        sc_name = sc.get("name") if sc else None
        sconst = ac.get("second_constant", 0)
        os_ = ac.get("output_signal", {}).get("name", "")
        # encode: type=1(arith), x,y, first_signal, op, second_signal_or_nil, second_constant, output_signal
        lines.append(f'{{1,{p["x"]},{p["y"]},"{fs}","{op}",{("\""+sc_name+"\"") if sc_name else "nil"},{sconst},"{os_}"}}')
    # deciders are numerous (gates) but those exist already typically (only 2 failures total across whole build) - skip for simplicity, repair pass handles wires only for those

print(f"total arithmetic relay/combinator entries: {len(lines)}")
lua_array = "{" + ",".join(lines) + "}"
with open("repair_entities.lua_data", "w") as f:
    f.write(lua_array)
print("bytes:", len(lua_array))
