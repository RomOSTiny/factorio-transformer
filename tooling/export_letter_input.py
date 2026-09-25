"""
Additive letter-input layer: lets the player select a LETTER-ICON signal
(signal-A..signal-Z, signal-white for space) on each in_p constant
combinator instead of manually computing and typing a number 1-27 on
signal-check. Does NOT touch or regenerate the existing 300-syllable build
- generates a single Lua command that ADDS a small translation layer near
each in_p, reusing that entity as-is (it keeps broadcasting whatever
signal the player sets - the checker layer below just reads it).

Architecture (mirrors export_full.py's syllable-detector/collector pattern,
just condensed - 27 checks instead of up to 300, single condition/output
instead of multi):

  in_p (existing) --RED--> read-relay chain (north, hop=8, signal-each
      passthrough) --RED--> up to 4 letter-checker deciders per relay hop
      (condition: signal-<LETTER> > 0, output: signal-check = <code>)
      --GREEN--> write-collector chain (parallel column, hop=8, back south)
      --RED--> back onto in_p's own network (so the EXISTING code_w_k
      arithmetic combinators, which already read signal-check from in_p,
      pick up the translated value with zero changes downstream)

Placed NORTH of the input row (negative y) - that whole direction is empty
in the existing build (everything else was built going south/down from
y=0), so no collision risk with anything already placed.

Real-world placement offset (0, -340) is the one census_300.py has
consistently detected all session - reused directly, not re-derived,
since the player hasn't moved anything between then and now.

Wire connector IDs (Factorio 2.0 defines.wire_connector_id, confirmed via
draftsman.constants.WireConnectorID): input_red=1, input_green=2,
output_red=3, output_green=4. A constant-combinator is NOT dual-
connectable - it has only ONE connector per color (circuit_red=1,
circuit_green=2, same numeric values as "input" - using "output"=3/4
against a constant-combinator would be wrong). in_p is the only constant-
combinator this script touches, so it's special-cased to always use 1/2.
"""

import math

POS_SPACING = 2
CHECK_SIGNAL = "signal-check"
OFFSET_X, OFFSET_Y = 0.0, -340.0
RELAY_HOP = 8
BAND_SIZE = 4
N_BANDS = math.ceil(27 / BAND_SIZE)  # 7

LETTER_SIGNALS = [f"signal-{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + ["signal-white"]
assert len(LETTER_SIGNALS) == 27

RED, GREEN = "red", "green"
IN_RED, IN_GREEN, OUT_RED, OUT_GREEN, CIRCUIT_RED, CIRCUIT_GREEN = 1, 2, 3, 4, 1, 2


def in_p_pos(p):
    return (round(p * POS_SPACING + 0.5 + OFFSET_X, 1), round(0.5 + OFFSET_Y, 1))


def build_position(p, entities, wires):
    ipx, ipy = in_p_pos(p)
    read_x, write_x = ipx, ipx + 1.0

    band_relay_ids = []
    prev_id, prev_conn = f"in_{p}", CIRCUIT_RED
    for b in range(N_BANDS):
        ry = round(ipy - RELAY_HOP * (b + 1), 1)
        rid = f"lin_read_{p}_{b}"
        entities.append({"id": rid, "kind": "relay", "x": read_x, "y": ry})
        wires.append((prev_id, prev_conn, rid, IN_RED, RED))
        prev_id, prev_conn = rid, OUT_RED
        band_relay_ids.append(rid)

    checkers_by_band = {b: [] for b in range(N_BANDS)}
    for idx in range(27):
        b, row = divmod(idx, BAND_SIZE)
        ry = round(ipy - RELAY_HOP * (b + 1) - (row + 1) * 2, 1)
        cid = f"lin_chk_{p}_{idx}"
        code = idx + 1
        entities.append({"id": cid, "kind": "checker", "x": read_x, "y": ry, "sig": LETTER_SIGNALS[idx], "code": code})
        wires.append((band_relay_ids[b], OUT_RED, cid, IN_RED, RED))
        checkers_by_band[b].append(cid)

    # BUG CAUGHT BEFORE HANDING TO THE PLAYER (self-review, not draftsman -
    # this whole script bypasses draftsman/collision-checking entirely by
    # generating raw create_entity Lua): first draft chained wid's OUTPUT
    # into prev_id's INPUT, i.e. band 5 -> band 6 -> band 5 -> ... - that
    # pushes the chain AWAY from in_p (toward the farthest band) instead of
    # toward it, so only band 0's own letters (A-D) would ever have reached
    # in_p; everything from bands 1-6 (E-Z, space) would relay off into the
    # farthest relay and dead-end there. Fixed: connect the FARTHER band's
    # (prev_id, processed earlier in this reversed loop) OUTPUT into the
    # CLOSER band's (wid) INPUT, so accumulated value flows band 6 -> 5 ->
    # ... -> 0 -> in_p, matching the order bands are actually created in.
    write_relay_id = {}
    prev_id = None
    for b in reversed(range(N_BANDS)):
        ry = round(ipy - RELAY_HOP * (b + 1), 1)
        wid = f"lin_write_{p}_{b}"
        entities.append({"id": wid, "kind": "relay", "x": write_x, "y": ry})
        write_relay_id[b] = wid
        for cid in checkers_by_band[b]:
            # BUG CAUGHT (2nd pass): the wire's connector ID itself IS the
            # color in Factorio 2.0 (1/3=red flavor, 2/4=green flavor) -
            # connect_to() takes no separate color argument at all (see the
            # generated Lua below). Sourcing this from OUT_RED(3) while
            # wiring to an IN_GREEN(2) target would connect mismatched
            # colors. Fixed: checker's green-flavored output is OUT_GREEN(4).
            wires.append((cid, OUT_GREEN, wid, IN_GREEN, GREEN))
        if prev_id is not None:
            wires.append((prev_id, OUT_GREEN, wid, IN_GREEN, GREEN))
        prev_id = wid

    # final hop lands back on in_p's single circuit connector, RED (same
    # network code_w_k already reads signal-check from). write_relay_id[0]
    # computes ONE internal value from its (green) input regardless of
    # which output connector reads it back out - wiring a NEW connection
    # via its RED-flavored output here is valid and gives the same value,
    # same "same combinator, different output connector color" reasoning
    # applies as for the checkers above (OUT_RED, not OUT_GREEN, to match
    # the RED target/color here).
    wires.append((write_relay_id[0], OUT_RED, f"in_{p}", CIRCUIT_RED, RED))


def lua_entity(e):
    if e["kind"] == "relay":
        return f'{{id="{e["id"]}",kind="relay",x={e["x"]},y={e["y"]}}}'
    else:
        return f'{{id="{e["id"]}",kind="checker",x={e["x"]},y={e["y"]},sig="{e["sig"]}",code={e["code"]}}}'


def lua_wire(w):
    id1, c1, id2, c2, color = w
    return f'{{"{id1}",{c1},"{id2}",{c2},"{color}"}}'


def verify_reachability(entities, wires, positions):
    """Self-check before this is ever handed to the player: for every
    checker, confirm a directed path exists from its OUTPUT to in_p,
    following only wires that leave from an OUTPUT-flavored connector
    (3 or 4) and land on an INPUT-flavored one (1 or 2, or in_p's single
    circuit connector) - modeling every relay/checker as a full pass-
    through node (their whole job is "reflect input as output"; this
    project doesn't build anything here that does otherwise). Also checks
    every checker's INPUT side is reachable FROM in_p (the read side),
    catching a broken/missing read-relay hop the same way.

    Building this graph and walking it is what caught two real bugs before
    either ever reached the game (see the two "BUG CAUGHT" comments above)
    - re-run on every generated batch, not trusted as fixed-once.
    """
    OUTPUT_CONNS, INPUT_CONNS = {3, 4}, {1, 2}
    forward = {}  # entity id -> set of entity ids reachable via ONE output->input wire
    backward = {}
    for id1, c1, id2, c2, _color in wires:
        # in_p is single-sided (constant-combinator) - its one connector
        # (id 1, CIRCUIT_RED, numerically the same as COMBINATOR_INPUT_RED)
        # acts as the SOURCE for anything reading it, unlike a dual-
        # connectable relay/checker where connector 1/2 really is input-
        # only. Special-cased by id prefix rather than connector number.
        is_source = c1 in OUTPUT_CONNS or id1.startswith("in_")
        is_sink = c2 in INPUT_CONNS or id2.startswith("in_")
        if is_source and is_sink:
            forward.setdefault(id1, set()).add(id2)
            backward.setdefault(id2, set()).add(id1)

    def bfs_reaches(graph, start, target):
        seen, stack = {start}, [start]
        while stack:
            node = stack.pop()
            if node == target:
                return True
            for nxt in graph.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    bad_out, bad_in = [], []
    for p in positions:
        target = f"in_{p}"
        for idx in range(27):
            cid = f"lin_chk_{p}_{idx}"
            if not bfs_reaches(forward, cid, target):
                bad_out.append(cid)
            if not bfs_reaches(backward, cid, target):  # walking backward from checker along forward-edges reversed = is checker reachable FROM in_p
                bad_in.append(cid)
    if bad_out or bad_in:
        raise AssertionError(f"Broken reachability - can't reach in_p (write side): {bad_out[:5]}{'...' if len(bad_out) > 5 else ''}; not reachable from in_p (read side): {bad_in[:5]}{'...' if len(bad_in) > 5 else ''}")


def build_command(positions):
    entities, wires = [], []
    for p in positions:
        build_position(p, entities, wires)
    verify_reachability(entities, wires, positions)

    entities_lua = ",".join(lua_entity(e) for e in entities)
    wires_lua = ",".join(lua_wire(w) for w in wires)

    return (
        "/c local entities={" + entities_lua + "}; "
        "local wires={" + wires_lua + "}; "
        "local surf=game.player.surface; local force=game.player.force; "
        "local id_lookup={}; "
        # pre-seed id_lookup with the EXISTING in_p entities this batch references
        + "".join(f'id_lookup["in_{p}"]=surf.find_entities_filtered{{type="constant-combinator",position={{{in_p_pos(p)[0]},{in_p_pos(p)[1]}}},radius=0.1}}[1]; ' for p in positions)
        + "local created,failed=0,0; "
        "for _,spec in pairs(entities) do "
        "local ok=pcall(function() "
        "local ent "
        'if spec.kind=="relay" then '
        'ent=surf.create_entity{name="arithmetic-combinator",position={spec.x,spec.y},force=force,raise_built=false}; '
        'ent.get_or_create_control_behavior().parameters={operation="*",first_signal={name="signal-each",type="virtual"},second_constant=1,output_signal={name="signal-each",type="virtual"}} '
        "else "
        'ent=surf.create_entity{name="decider-combinator",position={spec.x,spec.y},force=force,raise_built=false}; '
        'ent.get_or_create_control_behavior().parameters={conditions={{first_signal={name=spec.sig,type="virtual"},comparator=">",constant=0,compare_type="and"}},'
        f'outputs={{{{signal={{name="{CHECK_SIGNAL}",type="virtual"}},copy_count_from_input=false,constant=spec.code}}}}}} '
        "end "
        "id_lookup[spec.id]=ent "
        "end); "
        "if ok then created=created+1 else failed=failed+1 end "
        "end; "
        "local wok,wfail=0,0; "
        "for _,w in pairs(wires) do "
        "local ok=pcall(function() "
        "local e1=id_lookup[w[1]]; local e2=id_lookup[w[3]]; "
        "local wc1=e1.get_wire_connector(w[2],true); local wc2=e2.get_wire_connector(w[4],true); "
        "wc1.connect_to(wc2,false,defines.wire_origin.script) "
        "end); "
        "if ok then wok=wok+1 else wfail=wfail+1 end "
        "end; "
        'game.print("letter-input layer: entities created="..created..", failed="..failed..", wires ok="..wok..", failed="..wfail)'
    )


if __name__ == "__main__":
    # small-scale test: positions 0-1 only
    test_cmd = build_command([0, 1])
    with open("letter_input_test.txt", "w", encoding="utf-8") as f:
        f.write(test_cmd)
    print(f"Test command (positions 0-1): {len(test_cmd)} chars")

    # positions 0-1 already applied via the test command above and verified
    # working in-game - don't regenerate/reapply them (would create true
    # duplicate entities at the same spots, unlike the earlier repair
    # passes where create_entity on an occupied tile was a safe no-op:
    # THESE positions aren't occupied by matching entities, so a second
    # create_entity call would actually place a second overlapping set).
    REMAINING = list(range(2, 50))
    BATCH_POS = 5
    n_batches = math.ceil(len(REMAINING) / BATCH_POS)
    for b in range(n_batches):
        positions = REMAINING[b * BATCH_POS : (b + 1) * BATCH_POS]
        cmd = build_command(positions)
        with open(f"letter_input_batch_{b+1}.txt", "w", encoding="utf-8") as f:
            f.write(cmd)
    print(f"Remaining {len(REMAINING)} positions: {n_batches} batches of up to {BATCH_POS} positions each")
