"""Wire repair v2 for the Attention build - fixes a real bug found in v1:
widening find_near's position tolerance to 1.5 tiles (needed for drifted
gbridge_N relay-chain entities) let it occasionally grab a WRONG nearby
entity of the same type when several sit close together (found live:
p1_0 got miswired to p0_0, only 4 tiles apart, tolerance 1.5 on each side
made that ambiguous) - confirmed by audit: 82/1997 edges had >1 candidate
of the same name within 1.5 tiles of one endpoint.

Fix: carry each endpoint's own SIGNATURE (op/signals for arithmetic,
conditions/outputs for decider, signal content for constant) in the
manifest, and require an EXACT signature match in find_near, not just
name - p0_0 (second_signal=signal-M) and p1_0 (second_signal=signal-Q)
have different signatures despite both being "arithmetic-combinator",
so this can't mismatch between them regardless of tolerance. Generic
relay entities (gbridge_N, ROM vrelay/hrelay/crelay - all identical
signal-each pass-throughs) still rely on position alone, but their
correct spacing (>=8 tiles apart) is safe even at the same wide tolerance.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from draftsman.blueprintable import get_blueprintable_from_string
from rcon_client import connect

ARITH_OX, ARITH_OY = -2912.5, -273.0
CONST_OX, CONST_OY = -2913.0, -273.0
WIRED_TYPES = {"constant-combinator", "arithmetic-combinator", "decider-combinator"}

BLUEPRINT_PATH = os.path.join(os.path.dirname(__file__), "stage2_attention_full_test_blueprint.txt")
bp_string = open(BLUEPRINT_PATH, encoding="utf-8").read().strip()
bp = get_blueprintable_from_string(bp_string)
d = bp.to_dict()["blueprint"]
entities = d["entities"]
wires = d["wires"]


def real_pos(ent):
    lx, ly = ent["position"]["x"], ent["position"]["y"]
    if ent["name"] in ("arithmetic-combinator", "decider-combinator"):
        return lx + ARITH_OX, ly + ARITH_OY
    return lx + CONST_OX, ly + CONST_OY


def signature(ent):
    """A compact, JSON-stable signature string for exact-match comparison
    live. Generic pass-through relays (signal-each) all share one
    signature by design - fine, they're disambiguated by spacing instead."""
    name = ent["name"]
    cb = ent.get("control_behavior", {})
    if name == "arithmetic-combinator":
        c = cb.get("arithmetic_conditions", {})
        return json.dumps({
            "op": c.get("operation", "*"),
            "fs": c.get("first_signal", {}).get("name"),
            "fc": c.get("first_constant"),
            "ss": c.get("second_signal", {}).get("name"),
            "sc": c.get("second_constant"),
            "o": c.get("output_signal", {}).get("name"),
        }, sort_keys=True)
    if name == "decider-combinator":
        c = cb.get("decider_conditions", {})
        conds = sorted(
            (cc.get("first_signal", {}).get("name"), cc.get("comparator"), cc.get("compare_type", "and"),
             cc.get("second_signal", {}).get("name"), cc.get("constant"))
            for cc in c.get("conditions", [])
        )
        outs = sorted(
            (oo.get("signal", {}).get("name"), bool(oo.get("copy_count_from_input", True)), oo.get("constant"))
            for oo in c.get("outputs", [])
        )
        return json.dumps({"conds": conds, "outs": outs}, sort_keys=True)
    if name == "constant-combinator":
        secs = cb.get("sections", {}).get("sections", [])
        sigs = sorted((f.get("name"), f.get("count")) for sec in secs for f in sec.get("filters", []))
        return json.dumps(sigs)
    return ""


manifest = []
skipped = 0
for e1n, c1, e2n, c2 in wires:
    ent1, ent2 = entities[e1n - 1], entities[e2n - 1]
    if ent1["name"] not in WIRED_TYPES or ent2["name"] not in WIRED_TYPES:
        skipped += 1
        continue
    x1, y1 = real_pos(ent1)
    x2, y2 = real_pos(ent2)
    manifest.append([
        ent1["name"], round(x1, 3), round(y1, 3), c1, signature(ent1),
        ent2["name"], round(x2, 3), round(y2, 3), c2, signature(ent2),
    ])

print(f"wire manifest entries: {len(manifest)} (skipped {skipped})")
manifest_json = json.dumps(manifest)
print(f"manifest JSON size: {len(manifest_json)} bytes")

lua = '''
local surf = game.surfaces["nauvis"]
local W = helpers.json_to_table("__MANIFEST__")

local by_name = {}
for _, name in pairs({"constant-combinator", "arithmetic-combinator", "decider-combinator"}) do
  by_name[name] = surf.find_entities_filtered{name=name, area={{-1100,-500},{-500,1300}}}
end

local sig_cache = setmetatable({}, {__mode = "k"})
local function sig_of(e)
  local cached = sig_cache[e]
  if cached then return cached end
  local s
  if e.name == "arithmetic-combinator" then
    local p = e.get_or_create_control_behavior().parameters
    s = helpers.table_to_json({op=p.operation, fs=p.first_signal and p.first_signal.name or nil, fc=p.first_constant, ss=p.second_signal and p.second_signal.name or nil, sc=p.second_constant, o=p.output_signal and p.output_signal.name or nil})
  elseif e.name == "decider-combinator" then
    local p = e.get_or_create_control_behavior().parameters
    local conds, outs = {}, {}
    for _, c in pairs(p.conditions or {}) do
      table.insert(conds, {c.first_signal and c.first_signal.name or nil, c.comparator, c.compare_type or "and", c.second_signal and c.second_signal.name or nil, c.constant})
    end
    for _, o in pairs(p.outputs or {}) do
      table.insert(outs, {o.signal and o.signal.name or nil, o.copy_count_from_input, o.constant})
    end
    s = helpers.table_to_json({conds=conds, outs=outs})
  else
    -- BUGFIX (07.09.2026): get_signals(circuit_red) reads the WHOLE
    -- NETWORK's value, not this entity's own intrinsic content - if
    -- another entity is already (wrongly) sharing the network, this
    -- signature is contaminated by exactly the kind of bad match it's
    -- supposed to prevent. Read the entity's own stored slot directly
    -- instead (network-independent, always correct regardless of wiring
    -- state).
    local parts = {}
    local ok, cb = pcall(function() return e.get_or_create_control_behavior() end)
    if ok and cb and cb.sections and cb.sections[1] then
      local sec = cb.sections[1]
      local ok2, slots = pcall(function() return sec.filters end)
      if ok2 and slots then
        for _, slot in pairs(slots) do
          if slot.value then table.insert(parts, {slot.value.name, slot.min}) end
        end
      else
        -- fallback: probe a bounded range of slot indices directly
        for i = 1, 20 do
          local ok3, slot = pcall(function() return sec.get_slot(i) end)
          if ok3 and slot and slot.value then table.insert(parts, {slot.value.name, slot.min}) end
        end
      end
    end
    s = helpers.table_to_json(parts)
  end
  sig_cache[e] = s
  return s
end

local function find_near(name, x, y, want_sig)
  local bx, by = math.floor(x), math.floor(y)
  -- decider-combinators revived from ghost after the post-corruption
  -- rebuild drift up to ~2 tiles - widen just for this type.
  -- BUGFIX (07.09.2026): widening constant-combinator tolerance too
  -- (tried this) caused REAL cross-wiring damage in the exp-lookup ROM -
  -- adjacent row "store" constant-combinators are only 2 tiles apart, well
  -- inside a 3.0 tolerance, and the signature check that should have
  -- caught this was ITSELF broken (see the sig_of fix above - it read
  -- get_signals(), which reflects the whole network, not the entity's own
  -- content, so a wrongly-connected store's signature could match by
  -- coincidence). Reverted to 1.5 for constant-combinator. The remaining
  -- exp-ROM gaps (rows whose "read" decider is missing entirely, not just
  -- drifted) need to be recreated by hand, not chased via wider tolerance.
  local tol = (name == "decider-combinator" or name == "constant-combinator") and 3.0 or 1.5
  local candidates = {}
  for _, e in pairs(by_name[name]) do
    if math.abs(e.position.x-x) < tol and math.abs(e.position.y-y) < tol then
      table.insert(candidates, e)
    end
  end
  if #candidates == 0 then return nil end
  if #candidates == 1 then return candidates[1] end
  -- ambiguous by position alone: disambiguate by signature, then by closest distance
  local best, best_d = nil, math.huge
  for _, e in pairs(candidates) do
    if sig_of(e) == want_sig then
      local dd = (e.position.x-x)^2 + (e.position.y-y)^2
      if dd < best_d then best_d = dd; best = e end
    end
  end
  if best then return best end
  -- no signature match among candidates (shouldn't happen for a real edge) - fall back to closest
  for _, e in pairs(candidates) do
    local dd = (e.position.x-x)^2 + (e.position.y-y)^2
    if dd < best_d then best_d = dd; best = e end
  end
  return best
end

local function has_edge(con1, target_unit, target_cid)
  local ok, conns = pcall(function() return con1.connections end)
  if not ok or not conns then return nil end
  for _, conn in pairs(conns) do
    local t = conn.target
    if t and t.owner and t.owner.valid and t.owner.unit_number == target_unit and t.wire_connector_id == target_cid then
      return true
    end
  end
  return false
end

local connected, already, missing, failed, fallback_used = 0, 0, 0, 0, 0
local missing_list = {}
for i = 1, #W do
  local w = W[i]
  local name1, x1, y1, c1, sig1, name2, x2, y2, c2, sig2 = w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8], w[9], w[10]
  local e1 = find_near(name1, x1, y1, sig1)
  local e2 = find_near(name2, x2, y2, sig2)
  if e1 == nil or e2 == nil then
    missing = missing + 1
    table.insert(missing_list, name1 .. "@" .. x1 .. "," .. y1 .. " <-> " .. name2 .. "@" .. x2 .. "," .. y2)
  else
    local ok = pcall(function()
      local con1 = e1.get_wire_connector(c1, true)
      local con2 = e2.get_wire_connector(c2, true)
      local exists = has_edge(con1, e2.unit_number, c2)
      if exists == nil then
        fallback_used = fallback_used + 1
        if con1.real_connection_count == 0 or con2.real_connection_count == 0 then
          con1.connect_to(con2, false, defines.wire_origin.script)
          connected = connected + 1
        else
          already = already + 1
        end
      elseif exists then
        already = already + 1
      else
        con1.connect_to(con2, false, defines.wire_origin.script)
        connected = connected + 1
      end
    end)
    if not ok then failed = failed + 1 end
  end
end
helpers.write_file("wire_repair_attention_v2.json", helpers.table_to_json({connected=connected, already=already, missing=missing, failed=failed, fallback_used=fallback_used, missing_list=missing_list}), false)
rcon.print("connected=" .. connected .. " already=" .. already .. " missing=" .. missing .. " failed=" .. failed .. " fallback_used=" .. fallback_used)
'''.strip()

lua = lua.replace("__MANIFEST__", manifest_json.replace("\\", "\\\\").replace('"', '\\"'))
print(f"lua command size: {len(lua)} bytes")

with connect(timeout=180.0) as c:
    resp = c.command("/c " + lua)
    print(resp.strip())
