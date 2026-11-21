"""Build a device-model JSON from a Vivado geometry probe.

Usage:
    python tools/build_device_model.py probe_geometry_out.txt out.json \
        [--specials probe_specials.log]

The probe file is produced by tools/probe_geometry.tcl run against the real
part in Vivado (see that file for the recipe).  This script reduces it to
the JSON consumed by the package's device module.

IMPORTANT -- the frame constants below (FRAMES, BRAM_CONTENT_FRAMES,
PREAMBLE_FRAMES, OVERHEAD_BYTES) are 7-series values MEASURED from real
xc7z020 partial bitstreams (parsed with the package's bitparse module) and
corroborated by UG470 (101 words/frame) and Project X-Ray's public 7-series
documentation (CLB = 36 frames).  For a different device family, re-measure
them: generate two partial bitstreams with known pblock rectangles, parse
them, and solve for the per-column-type frame counts before trusting the
frames objective.  The geometry part (columns, rows, pairs, forbidden
cells) is fully probe-derived and needs no such calibration.

The script asserts its reduction against the probe's own TOTAL lines, and
sanity-checks slice pairing and column heights, so a silently-misread probe
fails loudly.
"""
import json
import os
import sys

NROWS = 3                  # clock-region rows of a probe without section 6 (xc7z020)
FRAMES = {"CLB": 36, "BRAM": 28, "DSP": 28, "OTHER30": 30}
BRAM_CONTENT_FRAMES = 128
FRAME_BYTES = 404          # 101 words x 4 (UG470 frame length)
PREAMBLE_FRAMES = 228      # measured: identical fixed preamble in partials
OVERHEAD_BYTES = 452       # measured: pre-sync header + command words

SLICES_PER_CELL = 100      # a CLB tile column = 2 slice columns x 50 sites/region
LUT_PER_CELL = 400
FF_PER_CELL = 800
RAMB36_PER_CELL = 10
RAMB18_PER_CELL = 20
DSP_PER_CELL = 20


# Interconnect cost classes that are general routing (the switch-box wires a
# route travels on); pin feeds, bounces, clocks and tie-offs are not.
ROUTING_COSTS = ("SINGLE", "DOUBLE", "HQUAD", "VQUAD", "BENTQUAD",
                 "HLONG", "VLONG", "VLONG12")
# The horizontal length-1 wires, where Vivado 2019.1 puts partition pins: on
# xc7z020 (get_pplocs) all 19,128 PPLOCs of twelve measured regions sat on
# one of them; only the two regions too small for their pins (10 slice cols
# x 1 row, 1,594 pins each, where routing failed at a 20-pin tile pair)
# spilled 7 % onto vertical singles.
PPLOC_WIRES = ("EL1BEG", "ER1BEG", "WL1BEG", "WR1BEG")


def routing_facts(probe_path):
    """Reduce the probe's interconnect inventory (INTW lines) to per-tile
    counts: routing wires named in a tile, the interconnect rows (sum dy) and
    columns (sum dx) those wires cross, and the partition-pin wires.  Taken as
    the most common inventory over the sampled tiles -- tiles at the device
    edge or the processor-subsystem hole see truncated or jumping wires."""
    tiles = {}
    for ln in open(probe_path):
        if not ln.startswith("INTW "):
            continue
        _, tile, wire, cost, dx, dy = ln.split()
        if cost not in ROUTING_COSTS:
            continue
        t = tiles.setdefault(tile, [0, 0, 0, 0])
        t[0] += 1
        t[1] += int(dy)
        t[2] += int(dx)
        if any(wire.startswith(p) for p in PPLOC_WIRES):
            t[3] += 1
    if not tiles:
        return None

    def mode(k):
        counts = {}
        for t in tiles.values():
            counts[t[k]] = counts.get(t[k], 0) + 1
        return max(sorted(counts), key=lambda v: counts[v])

    facts = {"wires_per_tile": mode(0),
             "vertical_crossings_per_tile": mode(1),
             "horizontal_crossings_per_tile": mode(2),
             "pploc_wires_per_tile": mode(3),
             "sampled_tiles": len(tiles)}
    # a misread probe fails loudly: every sampled tile carries the same
    # partition-pin wires, and the vertical inventory is near-uniform
    if any(t[3] != facts["pploc_wires_per_tile"] for t in tiles.values()):
        raise AssertionError("partition-pin wire count differs between tiles")
    if any(abs(t[1] - facts["vertical_crossings_per_tile"]) > 4
           for t in tiles.values()):
        raise AssertionError("vertical routing inventory not uniform")
    one_way = one_way_facts(probe_path)
    if one_way:
        v = one_way["north"] + one_way["south"] + one_way["vertical_either"]
        h = one_way["east"] + one_way["west"] + one_way["horizontal_either"]
        if v != facts["vertical_crossings_per_tile"] or \
                h != facts["horizontal_crossings_per_tile"]:
            raise AssertionError("one-way crossings %d / %d do not add up to "
                                 "%d / %d" % (v, h,
                                              facts["vertical_crossings_per_tile"],
                                              facts["horizontal_crossings_per_tile"]))
        facts["one_way_crossings_per_tile"] = one_way
    return facts


LONG_COSTS = ("HLONG", "VLONG", "VLONG12")


def one_way_facts(probe_path):
    """The crossings of a cut line per interconnect tile, by the direction a
    signal can take across it (probe INTD lines: a node's reach east, west,
    north and south of the tile it is named in, its driver end).  A one-way
    wire crosses only in the direction it reaches; a long line, driven at
    any of its taps, either way.  Returns {north, south, vertical_either,
    east, west, horizontal_either} (most common over the sampled tiles), or
    None for a probe without INTD lines."""
    tiles = {}
    for ln in open(probe_path):
        if not ln.startswith("INTD "):
            continue
        _, tile, _wire, cost, e, w, n, s = ln.split()
        if cost not in ROUTING_COSTS:
            continue
        e, w, n, s = int(e), int(w), int(n), int(s)
        t = tiles.setdefault(tile, [0] * 6)
        if cost in LONG_COSTS or (n and s):
            t[2] += n + s
        else:
            t[0] += n
            t[1] += s
        if cost in LONG_COSTS or (e and w):
            t[5] += e + w
        else:
            t[3] += e
            t[4] += w
    if not tiles:
        return None

    def mode(k):
        counts = {}
        for t in tiles.values():
            counts[t[k]] = counts.get(t[k], 0) + 1
        return max(sorted(counts), key=lambda v: counts[v])

    return {"north": mode(0), "south": mode(1), "vertical_either": mode(2),
            "east": mode(3), "west": mode(4), "horizontal_either": mode(5)}


def name_xy(name):
    i = name.rfind("_X")
    base = name[i + 2:]
    j = base.find("Y")
    return int(base[:j]), int(base[j + 1:])


def build(probe_path, specials_log=None):
    slice_rows = {}       # slice site X -> rows where the column exists
    ramb36_rows = {}      # ramb36 site X -> rows
    dsp_rows = {}         # dsp48 site X -> rows
    slice_to_tile = {}    # slice site X -> tile col X (row 0)
    ramb_to_tile = {}     # ramb36 site X -> tile col X
    dsp_to_tile = {}      # dsp48 site X -> tile col X
    int_rows = {}         # (side, tile col X) -> rows where INT exists
    int_count = {}        # (tile col X, row) -> INT tiles (routing model)
    colrow = {}           # (family, site X) -> {row: sites} (probe section 6)
    general = any(ln.startswith("COLROW ") for ln in open(probe_path))

    for ln in open(probe_path):
        ln = ln.strip()
        if ln.startswith("COLROW "):
            _, fam, x, r, n = ln.split()
            colrow.setdefault((fam, int(x)), {})[int(r)] = int(n)
        elif ln.startswith("MAPLO "):
            _, site, tile = ln.split()
            sx, sy = name_xy(site)
            tx, ty = name_xy(tile)
            if site.startswith("SLICE_"):
                slice_to_tile[sx] = tx
            elif site.startswith("RAMB36_"):
                ramb_to_tile[sx] = tx
            elif site.startswith("DSP48_"):
                dsp_to_tile[sx] = tx
        elif general and ln.startswith("COL "):
            continue          # rows come from the per-row counts instead
        elif ln.startswith("COL SLICE_X"):
            parts = ln.split()
            x = int(parts[1][len("SLICE_X"):])
            n = int(parts[2][2:])
            slice_rows[x] = [0] if n == 50 else [0, 1, 2]
            if n not in (50, 150):
                raise AssertionError("unexpected slice column height " + ln)
        elif ln.startswith("COL RAMB36_X"):
            parts = ln.split()
            x = int(parts[1][len("RAMB36_X"):])
            n = int(parts[2][2:])
            ramb36_rows[x] = [0] if n == 10 else [0, 1, 2]
            if n not in (10, 30):
                raise AssertionError("unexpected bram column height " + ln)
        elif ln.startswith("COL DSP48_X"):
            parts = ln.split()
            x = int(parts[1][len("DSP48_X"):])
            n = int(parts[2][2:])
            dsp_rows[x] = [0] if n == 20 else [0, 1, 2]
            if n not in (20, 60):
                raise AssertionError("unexpected dsp column height " + ln)
        elif ln.startswith("MAP SLICE_"):
            _, site, tile = ln.split()
            sx, sy = name_xy(site)
            tx, ty = name_xy(tile)
            slice_to_tile[sx] = tx
        elif ln.startswith("MAPB RAMB36_"):
            _, site, tile = ln.split()
            sx, sy = name_xy(site)
            tx, ty = name_xy(tile)
            ramb_to_tile[sx] = tx
        elif ln.startswith("MAPD DSP48_"):
            _, site, tile = ln.split()
            sx, sy = name_xy(site)
            tx, ty = name_xy(tile)
            dsp_to_tile[sx] = tx
        elif ln.startswith("TILE "):
            _, col, row, ty, name = ln.split()
            if ty in ("INT_L", "INT_R"):
                x, y = name_xy(name)
                int_rows.setdefault((ty, x), set()).add(y // 50)
                int_count[(x, y // 50)] = int_count.get((x, y // 50), 0) + 1

    # ---- general parts: a cell (column x clock-region row) is fabric only
    # where the column has every site of the row (50 slices, 10 RAMB36, 20
    # DSP48); partly occluded cells are left out, so the model never counts
    # sites a region could not be given whole
    nrows = NROWS
    if general:
        full = {"SLICE": 50, "RAMB36": 10, "DSP48": 20}
        nrows = 1 + max(r for rows in colrow.values() for r in rows)
        for (fam, x), rows in colrow.items():
            got = sorted(r for r, n in rows.items() if n == full[fam])
            if fam == "SLICE":
                slice_rows[x] = got
            elif fam == "RAMB36":
                ramb36_rows[x] = got
            else:
                dsp_rows[x] = got

    # ---- fabric columns keyed by tile-name X -------------------------------
    cols = {}
    for sx, tx in slice_to_tile.items():
        c = cols.setdefault(tx, {"type": "CLB", "rows": slice_rows[sx],
                                 "slice_lo": sx, "slice_hi": sx})
        c["slice_lo"] = min(c["slice_lo"], sx)
        c["slice_hi"] = max(c["slice_hi"], sx)
        if set(c["rows"]) != set(slice_rows[sx]):
            raise AssertionError("slice pair row mismatch tile %d" % tx)
    for bx, tx in ramb_to_tile.items():
        cols[tx] = {"type": "BRAM", "rows": ramb36_rows[bx], "bram_site": bx}
    for dx, tx in dsp_to_tile.items():
        cols[tx] = {"type": "DSP", "rows": dsp_rows[dx], "dsp_site": dx}

    # sanity: each CLB tile col carries exactly one slice pair (2k, 2k+1)
    for tx, c in cols.items():
        if c["type"] == "CLB":
            if c["slice_hi"] - c["slice_lo"] != 1 or c["slice_lo"] % 2 != 0:
                raise AssertionError("bad slice pair at tile %d: %s" % (tx, c))

    # ---- special columns (no user sites): classify from INT presence -------
    all_x = sorted(cols.keys())
    lo_x, hi_x = all_x[0], all_x[-1]
    known = set(cols.keys())
    specials = []
    for x in range(lo_x, hi_x + 1):
        if x in known:
            continue
        rows = sorted(int_rows.get(("INT_L", x), set()) |
                      int_rows.get(("INT_R", x), set()))
        specials.append(x)
        cols[x] = {"type": "OTHER30", "rows": rows}

    # ---- INT pair map: (even x, odd x+1) back-to-back, per row -------------
    pairs = {}
    for x in range(lo_x - (lo_x % 2), hi_x + 1, 2):
        rl = int_rows.get(("INT_L", x), set())
        rr = int_rows.get(("INT_R", x + 1), set())
        both = sorted(rl & rr)
        if both:
            pairs[x] = both

    model = {
        "nrows": nrows,
        "frames": FRAMES,
        "bram_content_frames": BRAM_CONTENT_FRAMES,
        "frame_bytes": FRAME_BYTES,
        "preamble_frames": PREAMBLE_FRAMES,
        "overhead_bytes": OVERHEAD_BYTES,
        "per_cell": {"slices": SLICES_PER_CELL, "lut": LUT_PER_CELL,
                     "ff": FF_PER_CELL, "ramb36": RAMB36_PER_CELL,
                     "ramb18": RAMB18_PER_CELL, "dsp": DSP_PER_CELL},
        "columns": {str(x): cols[x] for x in sorted(cols)},
        "pairs": {str(x): pairs[x] for x in sorted(pairs)},
        "specials": specials,
    }

    # ---- device totals: assert against the probe's own TOTAL lines ---------
    tot_sl = sum(SLICES_PER_CELL * len(c["rows"]) for c in cols.values()
                 if c["type"] == "CLB")
    tot_br = sum(RAMB36_PER_CELL * len(c["rows"]) for c in cols.values()
                 if c["type"] == "BRAM")
    tot_dsp = sum(DSP_PER_CELL * len(c["rows"]) for c in cols.values()
                  if c["type"] == "DSP")
    excluded = {}
    for ln in open(probe_path):
        for fam, got in (("SLICE", tot_sl), ("RAMB36", tot_br),
                         ("DSP48", tot_dsp)):
            if ln.startswith("TOTAL %s " % fam):
                n = int(ln.split()[2])
                if general:
                    # the sites of partly occluded cells are not counted
                    assert got <= n, (got, ln)
                    if got < n:
                        excluded[fam] = n - got
                else:
                    assert got == n, (got, ln)
    model["totals"] = {"slices": tot_sl, "lut": tot_sl * 4, "ff": tot_sl * 8,
                       "ramb36": tot_br, "dsp": tot_dsp}
    if excluded:
        model["excluded_sites"] = excluded

    # ---- partition-pin routability facts (probe section 5) ------------------
    # Interconnect tiles per fabric cell: one INT tile per site row, the same
    # in every fabric column (asserted).  A special column's INT tiles carry
    # no sites, so a site-range pblock cannot own them: they stay static
    # (measured: no module routing on INT_R_X33 in two routed regions that
    # covered it), and only CLB/BRAM/DSP columns route a region's module.
    facts = routing_facts(probe_path)
    if facts is not None:
        per_cell = set(n for (x, r), n in int_count.items()
                       if x in cols and cols[x]["type"] != "OTHER30"
                       and r in cols[x]["rows"])
        if len(per_cell) != 1:
            raise AssertionError("INT tiles per cell not uniform: %s"
                                 % sorted(per_cell))
        facts["int_tiles_per_cell"] = per_cell.pop()
        facts["module_routing_types"] = ["CLB", "BRAM", "DSP"]
        # the interconnect tile type of each column (pin plans name INT tiles)
        sides = {}
        for (side, x) in int_rows:
            if x in cols:
                if sides.get(x, side) != side:
                    raise AssertionError("column %d has INT_L and INT_R" % x)
                sides[x] = side
        facts["int_tile_types"] = {str(x): sides[x] for x in sorted(sides)}
        model["routing"] = facts
    # ---- special columns that cost a CLB column (tools/probe_specials.py) --
    # special x -> the CLB columns Vivado prohibits placement in while a
    # region covers x (its interconnect pair is split against static)
    if specials_log:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from probe_specials import parse_log
        lost_sites = parse_log(specials_log)
        missing = sorted(set(specials) - set(lost_sites))
        if missing:
            raise AssertionError("probe_specials log lacks specials %s" % missing)
        lost = {}
        for x, sxs in lost_sites.items():
            cs = sorted(set(slice_to_tile[sx] for sx in sxs))
            if any(cols.get(c, {}).get("type") != "CLB" for c in cs):
                raise AssertionError("special %d splits a non-CLB column: %s"
                                     % (x, cs))
            lost[x] = cs
        model["special_splits"] = {str(x): sorted(cs)
                                   for x, cs in sorted(lost.items()) if cs}
    return model


def main():
    args = sys.argv[1:]
    specials_log = None
    if "--specials" in args:
        k = args.index("--specials")
        specials_log = args[k + 1]
        del args[k:k + 2]
    if len(args) != 2:
        print(__doc__)
        return 2
    probe_path, out_path = args
    m = build(probe_path, specials_log)
    with open(out_path, "w") as f:
        json.dump(m, f, indent=1)
    print("device model written to %s: %d columns, %d pairs, specials=%s"
          % (out_path, len(m["columns"]), len(m["pairs"]), m["specials"]))
    print("totals:", m["totals"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
