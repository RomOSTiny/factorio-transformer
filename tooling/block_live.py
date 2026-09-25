"""Generic live operations for a generated block (blueprint + idmap) over RCON.

    blk = LiveBlock("x_blueprint.txt", "x_ids.json", TX, TY)
    blk.recon() / blk.clear() / blk.build() / blk.verify()
    blk.set_const("q_src", {"signal-A": 5}) ; blk.read("att_sink", "circuit_red")
Positions come from the blueprint (entity centres) + an offset measured on the block's unique
electric-energy-interface. verify() is read-only: every entity and every circuit wire of the
blueprint (combinators of all kinds, constants, poles) against the world, plus combinator statuses.
"""
import base64
import json
import zlib

import rcon_client

S = 'local s = game.surfaces["nauvis"]; '
FIND = ('local function F(n, x, y) local r = s.find_entities_filtered{name=n, position={x, y}, radius=0.3}; '
        'if #r == 1 then return r[1] end; error("find " .. n .. " at " .. x .. "," .. y .. " -> " .. #r) end; '
        'local function SIG(e, cid) local t = {}; for _, v in pairs(e.get_signals(defines.wire_connector_id[cid]) or {}) do '
        't[v.signal.name] = v.count end; return t end; ')


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


class LiveBlock:
    def __init__(self, bp_file, ids_file, tx, ty, margin=30, timeout=120.0):
        self.bp_string = open(bp_file).read().strip()
        self.bp = json.loads(zlib.decompress(base64.b64decode(self.bp_string[1:])))["blueprint"]
        self.ids = {e["id"]: e for e in json.load(open(ids_file))}
        xs = [e["x"] for e in self.ids.values()]; ys = [e["y"] for e in self.ids.values()]
        self.tx, self.ty = tx, ty
        self.hx, self.hy = (max(xs) - min(xs)) / 2 + margin, (max(ys) - min(ys)) / 2 + margin
        self.area = f"{{{{{tx - self.hx},{ty - self.hy}}},{{{tx + self.hx},{ty + self.hy}}}}}"
        self.c = rcon_client.connect(timeout=timeout)
        self.off = None

    def lua(self, body):
        out = self.c.command("/sc local ok, err = pcall(function() " + body +
                             " end) if not ok then rcon.print('LUA_ERROR ' .. tostring(err)) end")
        if "LUA_ERROR" in out:
            raise RuntimeError(out)
        return out

    def jlua(self, body):
        return json.loads(self.lua(body))

    def chunk_radius(self):
        return int(max(self.hx, self.hy) // 32) + 2

    def recon(self):
        return self.lua(S + f's.request_to_generate_chunks({{{self.tx},{self.ty}}}, {self.chunk_radius()}); '
                        's.force_generate_chunk_requests(); local cnt = {}; '
                        f'for _, e in pairs(s.find_entities_filtered{{area={self.area}}}) do cnt[e.type] = (cnt[e.type] or 0) + 1 end; '
                        f'local w = s.count_tiles_filtered{{area={self.area}, collision_mask="water_tile"}}; '
                        'rcon.print("water=" .. w .. " " .. helpers.table_to_json(cnt))')

    def clear(self):
        return self.lua(S + f'local n = 0; for _, e in pairs(s.find_entities_filtered{{area={self.area}, force="player"}}) do '
                        'if e.type ~= "character" then e.destroy(); n = n + 1 end end; rcon.print("destroyed=" .. n)')

    def build(self):
        log = [self.lua(S + f's.request_to_generate_chunks({{{self.tx},{self.ty}}}, {self.chunk_radius()}); '
                        's.force_generate_chunk_requests(); local inv = game.create_inventory(1); '
                        f'inv[1].set_stack{{name="blueprint"}}; inv[1].import_stack("{self.bp_string}"); '
                        f'local built = inv[1].build_blueprint{{surface=s, force=game.forces["player"], '
                        f'position={{x={self.tx}, y={self.ty}}}, force_build=true}}; inv.destroy(); rcon.print("built=" .. #built)').strip()]
        for _ in range(500):
            r = self.jlua(S + f'local g = s.find_entities_filtered{{area={self.area}, type="entity-ghost", limit=400}}; local n = 0; '
                          'for _, x in pairs(g) do if x.valid and x.revive{raise_revive=false} then n = n + 1 end end; '
                          f'rcon.print(helpers.table_to_json({{tried=#g, revived=n, left=s.count_entities_filtered{{area={self.area}, type="entity-ghost"}}}}))')
            log.append(r)
            if r["left"] == 0 or r["revived"] == 0:
                break
        return log

    def offset(self):
        if self.off is None:
            eei = self.ids["power_source"]
            live = self.jlua(S + f'local e = s.find_entities_filtered{{area={self.area}, name="electric-energy-interface"}}; '
                             'rcon.print(helpers.table_to_json({n=#e, x=e[1] and e[1].position.x, y=e[1] and e[1].position.y}))')
            assert live["n"] == 1, live
            self.off = (live["x"] - eei["x"], live["y"] - eei["y"])
        return self.off

    def world(self, e):
        ox, oy = self.offset()
        return e["name"], round(e["position"]["x"] + ox, 3), round(e["position"]["y"] + oy, 3)

    def at(self, eid):
        ox, oy = self.offset()
        e = self.ids[eid]
        return f'"{e["name"]}", {e["x"] + ox}, {e["y"] + oy}'

    def verify(self, chunk=4000):
        num = {e["entity_number"]: e for e in self.bp["entities"]}
        ents = [list(self.world(e)) for e in self.bp["entities"]]
        wires = [[*self.world(num[a]), ca, *self.world(num[b]), cb] for a, ca, b, cb in self.bp.get("wires", [])
                 if ca <= 4 and cb <= 4]
        res = dict(entities=len(ents), missing_entities=0, duplicates=0, miss_list=[], wires=len(wires),
                   wires_ok=0, wires_missing=0, bad_wires=[])
        for i in range(0, len(ents), chunk):
            r = self.jlua(S + f'local E = helpers.json_to_table("{esc(json.dumps(ents[i:i + chunk]))}"); local miss, dup = {{}}, 0; '
                          'for i = 1, #E do local r = s.find_entities_filtered{name=E[i][1], position={E[i][2], E[i][3]}, radius=0.3}; '
                          'if #r == 0 then table.insert(miss, E[i][1] .. "@" .. E[i][2] .. "," .. E[i][3]) elseif #r > 1 then dup = dup + 1 end end; '
                          'rcon.print(helpers.table_to_json({n=#miss, dup=dup, list={table.unpack(miss, 1, 10)}}))')
            res["missing_entities"] += r["n"]; res["duplicates"] += r["dup"]; res["miss_list"] += list(r.get("list") or [])
        for i in range(0, len(wires), chunk):
            r = self.jlua(S + 'local function F(n, x, y) local r = s.find_entities_filtered{name=n, position={x, y}, radius=0.3}; '
                          'if #r == 1 then return r[1] end; return nil end; '
                          f'local WW = helpers.json_to_table("{esc(json.dumps(wires[i:i + chunk]))}"); local ok, bad = 0, {{}}; '
                          'for i = 1, #WW do local w = WW[i]; local a, b = F(w[1], w[2], w[3]), F(w[5], w[6], w[7]); local found = false; '
                          'if a and b then for _, cn in pairs(a.get_wire_connector(w[4], true).connections) do '
                          'if cn.target.owner.unit_number == b.unit_number and cn.target.wire_connector_id == w[8] then found = true end end end; '
                          'if found then ok = ok + 1 elseif #bad < 10 then table.insert(bad, w) end end; '
                          'rcon.print(helpers.table_to_json({ok=ok, bad=bad}))')
            res["wires_ok"] += r["ok"]; res["bad_wires"] += list(r.get("bad") or [])
        res["wires_missing"] = res["wires"] - res["wires_ok"]
        res["status"] = self.jlua(S + f'local st = {{}}; for _, e in pairs(s.find_entities_filtered{{area={self.area}}}) do '
                                  'if e.type:find("combinator") then local k = e.name .. ":" .. tostring(e.status); st[k] = (st[k] or 0) + 1 end end; '
                                  'rcon.print(helpers.table_to_json(st))')
        res["ok"] = res["missing_entities"] == 0 and res["duplicates"] == 0 and res["wires_missing"] == 0 and \
            all(k.endswith(":1") for k in res["status"])
        return res

    def setter(self, eid, sigs):
        """Lua snippet that replaces the signals of constant `eid` (virtual signals)."""
        items = [[k, int(v)] for k, v in sigs.items() if v]
        return (f'do local cb = F({self.at(eid)}).get_or_create_control_behavior(); '
                'if cb.sections_count < 1 then cb.add_section() end; local sec = cb.get_section(1); '
                'for i = 1, 100 do sec.clear_slot(i) end; '
                f'local L = helpers.json_to_table("{esc(json.dumps(items))}"); '
                'for i = 1, #L do sec.set_slot(i, {value={type="virtual", name=L[i][1], quality="normal"}, min=L[i][2]}) end end; ')

    def set_consts(self, mapping):
        self.lua(S + FIND + "".join(self.setter(eid, sigs) for eid, sigs in mapping.items()))

    def read(self, reads):
        """reads: {key: (eid, connector_name)} -> {key: {signal: count}}"""
        body = ", ".join(f'["{k}"] = SIG(F({self.at(eid)}), "{cid}")' for k, (eid, cid) in reads.items())
        r = self.jlua(S + FIND + f'rcon.print(helpers.table_to_json({{{body}}}))')
        return {k: (r.get(k) if isinstance(r.get(k), dict) else {}) for k in reads}     # empty table -> "[]"

    def close(self):
        self.c.close()
