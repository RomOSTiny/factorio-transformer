"""
Power for the letter-input layer (2050 entities: 41 per position * 50
positions, spanning real y ~ -347.5 to -403.5, x ~ 0.5 to 101.5 - the
region strictly north of the original build, which only reaches up to
y ~ -341.5). Driven by a LIVE dump (factorio_ai_debug.json, extended
dump_signals_full_command.txt variant that also captures electric-pole
type) rather than a Python-side entity model, since these entities were
never built via draftsman/blueprint - reuses the same is_free/find_free_
spot/gap-fill algorithm shape as export_full.py's power section, just
reading real in-game positions instead of a local list.
"""

import json
import math

DUMP_FILE = r"C:\Users\natas\AppData\Roaming\Factorio\script-output\factorio_ai_debug.json"

dump = json.load(open(DUMP_FILE, encoding="utf-8"))

NEW_Y_CUTOFF = -343.0  # anything more negative than this is the new letter-input layer
powered_types = {"arithmetic-combinator", "decider-combinator"}

new_entities = [(r["x"], r["y"]) for r in dump if r["type"] in powered_types and r["y"] < NEW_Y_CUTOFF]
print(f"New letter-input entities needing power: {len(new_entities)} (expect 2050)")

existing_power = [(r["x"], r["y"], "substation" if r.get("name") == "substation" else "pole") for r in dump if r["type"] == "electric-pole"]
print(f"Existing power entities in dump: {len(existing_power)}")

# occupancy index (ALL entities in the dump, so new poles don't collide
# with anything - same BUCKET/is_free shape as export_full.py)
BUCKET = 2
occupied_bucket = {}
for r in dump:
    key = (int(r["x"] // BUCKET), int(r["y"] // BUCKET))
    occupied_bucket.setdefault(key, []).append((r["x"], r["y"]))


def is_free(cx, cy, min_dist_x=1.05, min_dist_y=1.4):
    kx, ky = int(cx // BUCKET), int(cy // BUCKET)
    for bx in (kx - 1, kx, kx + 1):
        for by in (ky - 1, ky, ky + 1):
            for ox, oy in occupied_bucket.get((bx, by), []):
                if abs(ox - cx) < min_dist_x and abs(oy - cy) < min_dist_y:
                    return False
    return True


def mark_occupied(cx, cy):
    key = (int(cx // BUCKET), int(cy // BUCKET))
    occupied_bucket.setdefault(key, []).append((cx, cy))


def find_free_spot(cx, cy, max_radius=10, min_dist_x=1.05, min_dist_y=1.4):
    if is_free(cx, cy, min_dist_x, min_dist_y):
        return (cx, cy)
    for r in range(1, max_radius + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                cand = (cx + dx, cy + dy)
                if is_free(*cand, min_dist_x, min_dist_y):
                    return cand
    return None


# ---- lattice over the new region's bounding box ----
xs = [x for x, y in new_entities]
ys = [y for x, y in new_entities]
min_x, max_x = min(xs), max(xs)
min_y, max_y = min(ys), max(ys)
print(f"New region bbox: ({min_x:.1f},{min_y:.1f}) to ({max_x:.1f},{max_y:.1f})")

# BUG FOUND 08.08.2026: substations have a 2x2 footprint - create_entity
# SILENTLY SNAPS a fractional (x.5) position to the nearest integer
# (confirmed empirically: requested -1.5 -> actual -1.0, requested 200.5
# -> actual 201.0, both times rounding toward +infinity - math.ceil).
# combinator positions are x.5 (their own footprint parity), so min_x
# inherited that fraction and every subsequent lattice x was x.5 too -
# every substation created was silently relocated ~0.5 tiles from where
# this script told the player/itself it would be, which is exactly why
# position-based lookups for linking/verification kept finding nothing:
# not a bulk-creation reliability issue, an unannounced coordinate snap.
# Y was already integer (input-row-derived combinators don't share X's
# offset), which is why only X ever visibly shifted in testing. Fixing at
# the source - round to where the entity will ACTUALLY end up - instead
# of chasing it after the fact.
min_x = math.ceil(min_x)

SUB_SPACING = 12
n_cols = math.ceil((max_x - min_x) / SUB_SPACING) + 1
n_rows = math.ceil((max_y - min_y) / SUB_SPACING) + 1

new_subs = []  # (id, x, y)
sub_lattice = {}
skipped = 0
for r in range(n_rows):
    for c in range(n_cols):
        sx, sy = min_x + c * SUB_SPACING, min_y + r * SUB_SPACING
        # skip candidates far from any entity needing power (same "sparsify
        # the lattice" fix as export_full.py's near_power_demand)
        near = any(math.hypot(sx - ex, sy - ey) <= 20 for ex, ey in new_entities)
        if not near:
            continue
        spot = find_free_spot(sx, sy)
        if spot is None:
            skipped += 1
            continue
        fx, fy = spot
        sid = f"lin_sub_{r}_{c}"
        new_subs.append((sid, fx, fy))
        mark_occupied(fx, fy)
        sub_lattice[(r, c)] = (sid, fx, fy)

print(f"Placed {len(new_subs)} new substations ({skipped} skipped)")

# ---- neighbor links within the new lattice ----
sub_links = []  # (id1, x1, y1, id2, x2, y2)
for (r, c), (sid, sx, sy) in sub_lattice.items():
    for nr, nc in ((r, c + 1), (r + 1, c)):
        nxt = sub_lattice.get((nr, nc))
        if nxt:
            nid, nx, ny = nxt
            sub_links.append((sid, sx, sy, nid, nx, ny))

# ---- link the new lattice into the EXISTING power network: nearest
# existing substation to the new lattice's closest row (y nearest to
# NEW_Y_CUTOFF), bridged with medium-electric-poles if beyond 18 tiles ----
existing_subs = [(x, y) for x, y, kind in existing_power if kind == "substation"]
closest_new = max(new_subs, key=lambda s: s[2])  # y closest to -343 (least negative) is nearest the existing structure
nearest_existing = min(existing_subs, key=lambda e: math.hypot(e[0] - closest_new[1], e[1] - closest_new[2]))
link_dist = math.hypot(nearest_existing[0] - closest_new[1], nearest_existing[1] - closest_new[2])
print(f"Nearest existing substation to new lattice: {nearest_existing}, distance {link_dist:.1f}")

bridge_poles = []  # (id, x, y)
bridge_power_links = []  # (id1, x1, y1, id2, x2, y2)
if link_dist <= 18:
    sub_links.append((closest_new[0], closest_new[1], closest_new[2], "EXISTING", nearest_existing[0], nearest_existing[1]))
else:
    n_hops = math.ceil(link_dist / 8)
    prev = ("EXISTING", nearest_existing[0], nearest_existing[1])
    for h in range(1, n_hops):
        t = h / n_hops
        tx = nearest_existing[0] + (closest_new[1] - nearest_existing[0]) * t
        ty = nearest_existing[1] + (closest_new[2] - nearest_existing[1]) * t
        spot = find_free_spot(tx, ty, max_radius=4, min_dist_x=0.55, min_dist_y=0.85) or (tx, ty)
        rid = f"lin_power_relay_{h}"
        bridge_poles.append((rid, spot[0], spot[1]))
        mark_occupied(*spot)
        bridge_power_links.append((prev[0], prev[1], prev[2], rid, spot[0], spot[1]))
        prev = (rid, spot[0], spot[1])
    bridge_power_links.append((prev[0], prev[1], prev[2], closest_new[0], closest_new[1], closest_new[2]))

print(f"Bridge poles needed: {len(bridge_poles)}")


# Root cause confirmed (see min_x = math.ceil(min_x) comment above): every
# substation position now requested is already where the entity will
# actually land, so no more silent position drift. Still checking the
# returned entity for nil (not just pcall success) and keeping batches
# small - cheap insurance, not load-bearing for correctness anymore.
BATCH_SIZE = 8


def build_create_batches():
    # the two diagnostic-test substations are being removed by hand before
    # this runs (see chat) - the lattice recomputed with the position fix
    # doesn't necessarily land on the same points, so no special-casing
    # here, just a clean recreate of every lattice point.
    to_create = [("substation", sid, x, y) for sid, x, y in new_subs]
    to_create += [("medium-electric-pole", rid, x, y) for rid, x, y in bridge_poles]

    batches = []
    for b in range(math.ceil(len(to_create) / BATCH_SIZE)):
        chunk = to_create[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
        parts = ['/c local surf=game.player.surface; local force=game.player.force; local created,failed=0,0; local failed_ids={}; ']
        for name, sid, x, y in chunk:
            parts.append(
                f'local ent=surf.create_entity{{name="{name}",position={{{x},{y}}},force=force,quality="legendary",raise_built=false}}; '
                f'if ent then created=created+1 else failed=failed+1; failed_ids[#failed_ids+1]="{sid}" end; '
            )
        parts.append('game.print("power create batch '
                      f'{b+1}/{math.ceil(len(to_create)/BATCH_SIZE)}'
                      ': created="..created..", failed="..failed); for _,f in pairs(failed_ids) do game.print("FAILED: "..f) end')
        batches.append("".join(parts))
    return batches


for i, batch in enumerate(build_create_batches()):
    with open(f"lin_power_create_batch_{i+1}.txt", "w", encoding="utf-8") as f:
        f.write(batch)
print(f"Wrote {len(build_create_batches())} creation batches ({BATCH_SIZE} substations each)")


def build_lua():
    parts = ['/c local surf=game.player.surface; local force=game.player.force; local id_lookup={}; local created,failed=0,0; ']
    ex, ey = nearest_existing
    parts.append(f'id_lookup["EXISTING"]=surf.find_entities_filtered{{name="substation",position={{{ex},{ey}}},radius=0.2}}[1]; ')

    for sid, x, y in new_subs:
        parts.append(f'local ok=pcall(function() id_lookup["{sid}"]=surf.create_entity{{name="substation",position={{{x},{y}}},force=force,quality="legendary",raise_built=false}} end); if ok then created=created+1 else failed=failed+1 end; ')
    for rid, x, y in bridge_poles:
        parts.append(f'local ok=pcall(function() id_lookup["{rid}"]=surf.create_entity{{name="medium-electric-pole",position={{{x},{y}}},force=force,quality="legendary",raise_built=false}} end); if ok then created=created+1 else failed=failed+1 end; ')

    parts.append('local linked,lfail=0,0; ')
    for id1, x1, y1, id2, x2, y2 in sub_links + bridge_power_links:
        parts.append(f'local ok=pcall(function() id_lookup["{id1}"].connect_neighbour(id_lookup["{id2}"]) end); if ok then linked=linked+1 else lfail=lfail+1 end; ')

    parts.append('game.print("letter-input power: created="..created..", failed="..failed..", links="..linked..", link_failed="..lfail)')
    return "".join(parts)


cmd = build_lua()
with open("letter_input_power.txt", "w", encoding="utf-8") as f:
    f.write(cmd)
print(f"Wrote letter_input_power.txt: {len(cmd)} chars")


def build_link_only_lua():
    # BUG FOUND 08.08.2026: connect_neighbour is NOT the right API in
    # Factorio 2.0 - power/copper wires ALSO moved to the wire_connector
    # system (confirmed: draftsman.constants.WireConnectorID includes
    # POLE_COPPER=5, in the SAME enum as the circuit connector ids 1-4
    # already proven working for the letter-input layer's own circuit
    # wiring). All 39 substations were already created successfully
    # (created=39, failed=0) - this only re-does the linking, finding each
    # one by its known position instead of re-creating it.
    parts = ['/c local surf=game.player.surface; local id_lookup={}; ']
    ex, ey = nearest_existing
    parts.append(f'id_lookup["EXISTING"]=surf.find_entities_filtered{{name="substation",position={{{ex},{ey}}},radius=0.2}}[1]; ')
    for sid, x, y in new_subs:
        parts.append(f'id_lookup["{sid}"]=surf.find_entities_filtered{{name="substation",position={{{x},{y}}},radius=0.2}}[1]; ')
    for rid, x, y in bridge_poles:
        parts.append(f'id_lookup["{rid}"]=surf.find_entities_filtered{{name="medium-electric-pole",position={{{x},{y}}},radius=0.2}}[1]; ')

    parts.append('local linked,lfail=0,0; ')
    for id1, x1, y1, id2, x2, y2 in sub_links + bridge_power_links:
        parts.append(
            f'local ok=pcall(function() '
            f'local w1=id_lookup["{id1}"].get_wire_connector(5,true); local w2=id_lookup["{id2}"].get_wire_connector(5,true); '
            f'w1.connect_to(w2,false,defines.wire_origin.script) '
            f'end); if ok then linked=linked+1 else lfail=lfail+1 end; '
        )
    parts.append('game.print("letter-input power LINK-ONLY: links="..linked..", link_failed="..lfail)')
    return "".join(parts)


link_cmd = build_link_only_lua()
with open("letter_input_power_link_only.txt", "w", encoding="utf-8") as f:
    f.write(link_cmd)
print(f"Wrote letter_input_power_link_only.txt: {len(link_cmd)} chars")
