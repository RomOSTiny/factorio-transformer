"""
Bridges the existing Display Panel's signal (ARGMAX_RESULT, already
broadcasting on its RED network at (203.5,-173.5)) back to a new Display
Panel placed next to the input row - same relay-chain pattern used
throughout export_full.py and the letter-input layer (signal-each
passthrough, hop <= 8 tiles), just a straight-line long-distance version.
No power included - handled separately by the player this time.
"""

import json
import math

EXISTING_PANEL_POS = (203.5, -173.5)
LANDING_POS = (-20.0, -341.0)  # west of the input row, clear open space
HOP = 8

CLASSES_FILE = "../training/classifier_weights.json"
CARDPUTER_FILE = "../data/intents_cardputer.json"
FACTORIO_FILE = "../data/intents_new_factorio.json"

weights = json.load(open(CLASSES_FILE, encoding="utf-8"))
CLASSES = weights["classes"]
cardputer = json.load(open(CARDPUTER_FILE, encoding="utf-8"))
factorio_new = json.load(open(FACTORIO_FILE, encoding="utf-8"))
response_by_class = {i["name"]: i["responses"][0] for i in cardputer["intents"] + factorio_new["intents"]}
response_by_class["fallback"] = cardputer["fallback"]["responses"][0]
CLASS_RESPONSES = [response_by_class[c] for c in CLASSES]

# WINNER_SIGNALS: same _pool-derived slice export_full.py used - recompute
# identically (same deterministic order from signal_data.raw.keys())
import sys

sys.path.insert(0, ".")
from draftsman.data import signals as signal_data

_reserved = {"signal-check", "signal-each", "signal-anything", "signal-everything", "signal-any-quality"}
_pool = [s for s in signal_data.raw.keys() if s not in _reserved]
N_WINDOWS = 48
WINNER_SIGNALS = _pool[N_WINDOWS + 350 + len(CLASSES) : N_WINDOWS + 350 + 2 * len(CLASSES)]
assert len(WINNER_SIGNALS) == len(CLASSES) == 50

# BUG FOUND 08.08.2026, confirmed empirically via 10 live in-game pcall
# tests (not guessed): draftsman's own per-signal "type" (signal_data.raw[
# name]["type"]) is NOT the string the LIVE Lua API's SignalID validator
# wants for several Space Age categories - the live API only recognizes a
# smaller/differently-named set. Mapping confirmed live: asteroid->entity,
# planet->space-location, gun->item; recipe, space-location and asteroid-
# chunk happened to already match. This is why the ORIGINAL Display Panel
# (built via blueprint import/revive, which goes through the game's
# blueprint deserializer instead of this live validator) never hit this -
# the two code paths accept different type vocabularies for the exact
# same signals.
LIVE_TYPE_OVERRIDE = {"asteroid": "entity", "planet": "space-location", "gun": "item"}


def live_signal_type(name):
    t = signal_data.raw[name]["type"]
    return LIVE_TYPE_OVERRIDE.get(t, t)

fx, fy = EXISTING_PANEL_POS
tx, ty = LANDING_POS
dist = math.hypot(tx - fx, ty - fy)
n_hops = math.ceil(dist / HOP)
print(f"Distance: {dist:.1f} tiles, {n_hops} hops")

hops = []  # (id, x, y)
for h in range(1, n_hops + 1):
    t = h / n_hops
    hops.append((f"dbridge_{h}", fx + (tx - fx) * t, fy + (ty - fy) * t))

# (id1, conn1, id2, conn2) tuples - kept as plain Python data, not
# pre-rendered strings, so nothing downstream needs to re-parse Lua syntax
wire_links = [("EXISTING_PANEL", 1, hops[0][0], 1)]
for i in range(len(hops) - 1):
    wire_links.append((hops[i][0], 3, hops[i + 1][0], 1))

# BUG FOUND 08.08.2026, second attempt: fixing the type per WINNER_SIGNALS
# entry (recipe/asteroid/planet/gun/space-location) got further but still
# failed - "Unknown signal type: asteroid in property tree" - the live
# LuaDisplayPanelControlBehavior.messages setter apparently only accepts
# the classic item/fluid/virtual signal categories in a condition, not the
# newer Space Age ones, even though those same signals work fine as
# regular circuit signals (confirmed - the ORIGINAL panel, built via
# blueprint import/revive rather than a live .messages= call, shows the
# exact same 50 signals with no complaint - so this is specifically a
# live-API strictness quirk, not a real usability limit on the signals
# themselves). ALL 50 WINNER_SIGNALS turned out to be non-classic types -
# not a fixable per-entry swap. Fix: 50 small translator deciders at the
# bridge's endpoint, each reading its own WINNER_SIGNALS[k] (whatever
# exotic type) and re-emitting a plain virtual-signal that the new panel's
# conditions check instead - same "translate to a friendlier signal"
# pattern as the letter-input layer's own checkers.
_reserved_virtual = set(signal_data.raw.keys()) - {s for s in signal_data.raw if signal_data.raw[s]["type"] == "virtual-signal"}
_letters_used = {f"signal-{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"} | {"signal-white", "signal-check", "signal-each", "signal-anything", "signal-everything", "signal-any-quality"}
_virtual_pool = [s for s in signal_data.raw if signal_data.raw[s]["type"] == "virtual-signal" and s not in _letters_used]
SAFE_SIGNALS = _virtual_pool[:50]
assert len(SAFE_SIGNALS) == 50

# two 25-cell sub-clusters (6x6 grid, 25 used, spacing 2 -> corner ~7.1
# tiles, the exact safe budget export_full.py's argmax layer already
# proved at this same n=25/spacing=2 shape)
translator_entities = []  # (id, x, y, cond_sig, cond_type, out_sig)
GRID_SIDE, SPACING = 6, 2


def grid_offset(i):
    return (i - (GRID_SIDE - 1) / 2) * SPACING


# clusters placed CLUSTER_GAP=14 apart (same margin export_full.py's own
# output/argmax layers used for adjacent 6x6 clusters) so the bridge
# between their two local collectors is a single short hop, and the new
# panel (sitting right between them) can reach either collector directly
CLUSTER_GAP = 14
cluster_centers = [(tx - CLUSTER_GAP / 2, ty - 20), (tx + CLUSTER_GAP / 2, ty - 20)]
for ci, (ccx, ccy) in enumerate(cluster_centers):
    for i in range(25):
        k = ci * 25 + i
        gx, gy = i % GRID_SIDE, i // GRID_SIDE
        ex, ey = ccx + grid_offset(gx), ccy + grid_offset(gy)
        translator_entities.append((f"dtrans_{k}", ex, ey, WINNER_SIGNALS[k], live_signal_type(WINNER_SIGNALS[k]), SAFE_SIGNALS[k]))

# each cluster's own local collector (signal-each passthrough) sits at
# its center (guaranteed empty - even 6x6 grid, offsets are always odd
# multiples of spacing, same "empty center" reasoning export_full.py uses
# throughout) - gathers that cluster's 25 SAFE_SIGNALS (all distinctly
# named, so no risk of the merge colliding two classes' signals together)
collector_ids = [f"dcol_{ci}" for ci in range(2)]

# bridge chain endpoint feeds each cluster's collector - both clusters are
# within reach of hops[-1] (20-ish tiles, needs a couple hops)
last_bridge_id = hops[-1][0]
feed_hops = {0: [], 1: []}
for ci, (ccx, ccy) in enumerate(cluster_centers):
    fx2, fy2 = tx, ty
    dist2 = math.hypot(ccx - fx2, ccy - fy2)
    nh2 = max(1, math.ceil(dist2 / HOP))
    prev = last_bridge_id
    chain = []
    for h in range(1, nh2 + 1):
        t = h / nh2
        px, py = fx2 + (ccx - fx2) * t, fy2 + (ccy - fy2) * t
        hid2 = f"dfeed_{ci}_{h}"
        chain.append((hid2, px, py))
        wire_links.append((prev, 3, hid2, 1))
        prev = hid2
    feed_hops[ci] = chain
    # last feed hop IS the cluster's collector position - reuse it as the
    # collector itself instead of a separate entity one hop further
    collector_ids[ci] = prev

for ci in range(2):
    for i in range(25):
        k = ci * 25 + i
        tid = f"dtrans_{k}"
        wire_links.append((collector_ids[ci], 3, tid, 1))  # collector's RED output broadcasts WINNER_SIGNALS types to every translator's RED input
        wire_links.append((tid, 4, collector_ids[ci], 2))  # translator's GREEN output feeds back onto the collector's GREEN side - keeps read/write on separate colors, same pattern used throughout this project

wire_links.append((collector_ids[0], 4, collector_ids[1], 2))  # merge the two clusters' collected GREEN outputs together
wire_links.append((collector_ids[1], 4, "NEW_PANEL", 2))  # panel reads the merged signals on its GREEN connector

messages_lua = ",".join(
    '{{text="{}",condition={{first_signal={{name="{}",type="virtual"}},comparator="=",constant=1}}}}'.format(
        CLASS_RESPONSES[k].replace('"', "'"), SAFE_SIGNALS[k]
    )
    for k in range(len(CLASSES))
)

# NOTE: `hops` (the main 35-hop bridge chain) was already created and
# confirmed in an earlier round (this script's first version) - only the
# NEW entities (per-cluster feed chains + 50 translators) need creating
# now. Relay entities (feed hops) are plain signal-each passthrough
# arithmetic-combinators, same as before; translators are single-
# condition/single-output deciders, same shape as the letter-input layer's
# own checkers.
all_feed_hops = feed_hops[0] + feed_hops[1]

BATCH_SIZE = 15
relay_batches = []
for b in range(math.ceil(len(all_feed_hops) / BATCH_SIZE)):
    chunk = all_feed_hops[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
    parts = ['/c local surf=game.player.surface; local force=game.player.force; local created,failed=0,0; ']
    for hid, x, y in chunk:
        parts.append(
            f'local ent=surf.create_entity{{name="arithmetic-combinator",position={{{x},{y}}},force=force,raise_built=false}}; '
            f'ent.get_or_create_control_behavior().parameters={{operation="*",first_signal={{name="signal-each",type="virtual"}},second_constant=1,output_signal={{name="signal-each",type="virtual"}}}}; '
            f'if ent then created=created+1 else failed=failed+1 end; '
        )
    parts.append(f'game.print("feed hop batch: created="..created..", failed="..failed)')
    relay_batches.append("".join(parts))

for i, batch in enumerate(relay_batches):
    with open(f"display_feed_create_{i+1}.txt", "w", encoding="utf-8") as f:
        f.write(batch)

translator_batches = []
for b in range(math.ceil(len(translator_entities) / BATCH_SIZE)):
    chunk = translator_entities[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
    # BUG FOUND 08.08.2026: the previous version set .parameters directly,
    # unguarded - the very first bad signal type threw a hard, uncaught
    # error that aborted the ENTIRE command mid-batch (confirmed in-game:
    # "Cannot execute command", only 1 of 15 entities in that batch ended
    # up created, with no parameters set at all). Wrapping in pcall this
    # time so one bad entity can't take the rest of the batch down with it
    # - same lesson as every other bulk-creation pass this session.
    parts = ['/c local surf=game.player.surface; local force=game.player.force; local created,failed=0,0; ']
    for tid, x, y, cond_sig, cond_type, out_sig in chunk:
        parts.append(
            f'do local ok=pcall(function() '
            f'local ent=surf.create_entity{{name="decider-combinator",position={{{x},{y}}},force=force,raise_built=false}}; '
            f'ent.get_or_create_control_behavior().parameters={{conditions={{{{first_signal={{name="{cond_sig}",type="{cond_type}"}},comparator=">",constant=0,compare_type="and"}}}},'
            f'outputs={{{{signal={{name="{out_sig}",type="virtual"}},copy_count_from_input=false,constant=1}}}}}} '
            f'end); if ok then created=created+1 else failed=failed+1 end end; '
        )
    parts.append(f'game.print("translator batch: created="..created..", failed="..failed)')
    translator_batches.append("".join(parts))

for i, batch in enumerate(translator_batches):
    with open(f"display_translator_create_{i+1}.txt", "w", encoding="utf-8") as f:
        f.write(batch)

print(f"Wrote {len(relay_batches)} feed-hop batches + {len(translator_batches)} translator batches")

# wiring + new panel, all in one command (small, ~n_hops+1 connections)
wire_cmd_parts = ['/c local surf=game.player.surface; local force=game.player.force; local id_lookup={}; ']
wire_cmd_parts.append(f'id_lookup["EXISTING_PANEL"]=surf.find_entities_filtered{{type="display-panel",position={{{EXISTING_PANEL_POS[0]},{EXISTING_PANEL_POS[1]}}},radius=1}}[1]; ')
for hid, x, y in hops:
    wire_cmd_parts.append(f'id_lookup["{hid}"]=surf.find_entities_filtered{{name="arithmetic-combinator",position={{{x},{y}}},radius=0.5}}[1]; ')
for hid, x, y in all_feed_hops:
    wire_cmd_parts.append(f'id_lookup["{hid}"]=surf.find_entities_filtered{{name="arithmetic-combinator",position={{{x},{y}}},radius=0.5}}[1]; ')
for tid, x, y, cond_sig, cond_type, out_sig in translator_entities:
    wire_cmd_parts.append(f'id_lookup["{tid}"]=surf.find_entities_filtered{{name="decider-combinator",position={{{x},{y}}},radius=0.5}}[1]; ')

wire_cmd_parts.append(
    # the earlier failed attempt likely already created the panel entity
    # itself (only the .parameters line after it threw) - look for it
    # first instead of blindly re-creating (would just collide/return nil)
    f'local panel=surf.find_entities_filtered{{type="display-panel",position={{{tx},{ty}}},radius=1}}[1]; '
    f'if not panel then panel=surf.create_entity{{name="display-panel",position={{{tx},{ty}}},force=force,raise_built=false}} end; '
    f'id_lookup["NEW_PANEL"]=panel; '
    # BUG FOUND 08.08.2026: the blueprint JSON export format calls this key
    # "parameters" (confirmed via draftsman decode earlier), but the LIVE
    # runtime LuaDisplayPanelControlBehavior object rejected that key
    # outright ("doesn't contain key parameters") - export format and
    # runtime API aren't the same shape here, unlike decider/arithmetic
    # combinators where both happened to agree. Trying "messages" instead
    # (matches draftsman's own Python constructor argument name for the
    # same data), wrapped in pcall this time so a second wrong guess can't
    # abort the whole command before the wiring loop below even runs like
    # it just did.
    f'local ok_msg,err_msg=pcall(function() panel.get_or_create_control_behavior().messages={{{messages_lua}}} end); '
    f'game.print("panel messages set: "..tostring(ok_msg).." "..tostring(err_msg)); '
)

wire_cmd_parts.append("local linked,lfail=0,0; ")
wire_cmd_parts.append("local fails={}; ")
for id1, c1, id2, c2 in wire_links:
    wire_cmd_parts.append(
        f'do local ok=pcall(function() local w1=id_lookup["{id1}"].get_wire_connector({c1},true); local w2=id_lookup["{id2}"].get_wire_connector({c2},true); w1.connect_to(w2,false,defines.wire_origin.script) end); '
        f'if ok then linked=linked+1 else lfail=lfail+1; fails[#fails+1]="{id1}({c1})--{id2}({c2}) e1="..tostring(id_lookup["{id1}"]).." e2="..tostring(id_lookup["{id2}"]) end end; '
    )
wire_cmd_parts.append('game.print("display bridge wiring: linked="..linked..", failed="..lfail); for _,f in pairs(fails) do game.print(f) end')

wire_cmd = "".join(wire_cmd_parts)
with open("display_bridge_wire_and_panel.txt", "w", encoding="utf-8") as f:
    f.write(wire_cmd)

print(f"Wrote 1 wiring/panel command ({len(wire_cmd)} chars), {len(wire_links)} total wire links")
