"""Emit floorplans as site-range constraints.

Two output formats:
  * ``pblocks.txt`` -- one block of site-range lines per region, blocks
    separated by a blank line, '#' comments (a simple exchange format some
    DPR build flows consume directly);
  * XDC -- Vivado Tcl constraints (create_pblock / resize_pblock /
    add_cells_to_pblock / RESET_AFTER_RECONFIG), syntax per UG909, and
    optionally a partition-pin plan (HD.PARTPIN_LOCS, ``partpin_plan``).

Site-range serialization is exact for the bundled device models: covered
tile columns map back to SLICE / DSP48 / RAMB18+RAMB36 site ranges.  On
7-series a clock-region row spans 50 slice rows, 20 DSP48 rows, 20 RAMB18
rows and 10 RAMB36 rows; those per-row site counts come from the device
model's per_cell table.
"""

SLICE_ROWS_PER_REGION = 50


def site_ranges(device, cols, rows):
    """Serialize a covered rectangle to a list of site-range strings.

    Round-trips the measured hand floorplans exactly (see tests/test_emit.py).
    """
    rows = sorted(rows)
    r0, r1 = rows[0], rows[-1]
    ranges = []
    clb = sorted(c for c in cols if device.col_type(c) == "CLB")
    if clb:
        lo = device.columns[clb[0]]["slice_lo"]
        hi = device.columns[clb[-1]]["slice_hi"]
        ranges.append("SLICE_X%dY%d:SLICE_X%dY%d"
                      % (lo, SLICE_ROWS_PER_REGION * r0,
                         hi, SLICE_ROWS_PER_REGION * r1 + SLICE_ROWS_PER_REGION - 1))
    dsp_n = device.per_cell["dsp"]
    dsp = sorted(device.columns[c]["dsp_site"] for c in cols
                 if device.col_type(c) == "DSP")
    if dsp:
        ranges.append("DSP48_X%dY%d:DSP48_X%dY%d"
                      % (dsp[0], dsp_n * r0, dsp[-1], dsp_n * r1 + dsp_n - 1))
    b18_n = device.per_cell["ramb18"]
    b36_n = device.per_cell["ramb36"]
    bram = sorted(device.columns[c]["bram_site"] for c in cols
                  if device.col_type(c) == "BRAM")
    if bram:
        ranges.append("RAMB18_X%dY%d:RAMB18_X%dY%d"
                      % (bram[0], b18_n * r0, bram[-1], b18_n * r1 + b18_n - 1))
        ranges.append("RAMB36_X%dY%d:RAMB36_X%dY%d"
                      % (bram[0], b36_n * r0, bram[-1], b36_n * r1 + b36_n - 1))
    return ranges


def pblocks_text(regions, header=None):
    """regions: list of (name, list-of-range-strings). Returns pblocks.txt text."""
    out = []
    if header:
        for ln in header.splitlines():
            out.append(("# " + ln).rstrip())
        out.append("")
    for k, (name, ranges) in enumerate(regions):
        if k:
            out.append("")
        out.append("# " + name)
        out.extend(ranges)
    return "\n".join(out) + "\n"


def xdc_text(regions, cells=None, reset_after_reconfig=True,
             snapping_mode=True, header=None):
    """regions: list of (name, list-of-range-strings).

    cells: optional dict region-name -> hierarchical cell path; when given,
    emits add_cells_to_pblock and HD.RECONFIGURABLE for that cell.
    Command syntax per UG909 (Vivado Design Suite User Guide: Partial
    Reconfiguration / Dynamic Function eXchange).
    """
    out = []
    if header:
        for ln in header.splitlines():
            out.append(("# " + ln).rstrip())
        out.append("")
    for name, ranges in regions:
        pb = "pblock_" + name
        out.append("create_pblock %s" % pb)
        if cells and name in cells:
            out.append("add_cells_to_pblock [get_pblocks %s] [get_cells [list %s]]"
                       % (pb, cells[name]))
        for rng in ranges:
            out.append("resize_pblock [get_pblocks %s] -add {%s}" % (pb, rng))
        if reset_after_reconfig:
            out.append("set_property RESET_AFTER_RECONFIG true [get_pblocks %s]" % pb)
        if snapping_mode:
            out.append("set_property SNAPPING_MODE ON [get_pblocks %s]" % pb)
        if cells and name in cells:
            out.append("set_property HD.RECONFIGURABLE true [get_cells %s]"
                       % cells[name])
        out.append("")
    return "\n".join(out)


def partpin_tiles(device, cols, rows, trim=1):
    """The interconnect tiles a region's partition pins may take, row by row:
    the region's module-routable columns (less the CLB columns covered
    special columns cost) over its interconnect rows, less ``trim`` rows at
    the region's top and bottom edge (two pins in one edge tile left a node
    overlap, RFP's GA build, 2026-11-18)."""
    rt = device.raw["routing"]
    types = rt["module_routing_types"]
    n = rt["int_tiles_per_cell"]
    lost = set(c for x in cols for c in device.special_splits.get(x, ()))
    pcols = [c for c in sorted(cols)
             if device.col_type(c) in types and c not in lost]
    rows = sorted(rows)
    y0 = n * rows[0] + trim
    y1 = n * rows[-1] + n - 1 - trim
    return ["%s_X%dY%d" % (rt["int_tile_types"][str(c)], c, y)
            for y in range(y0, y1 + 1) for c in pcols]


def partpin_plan(device, cols, rows, pins, pairs=(), per_tile=4, trim=1):
    """A partition-pin plan for one region: [(pin, INT tile)].

    pins: the region's partition pins (port bits; clock and other global
    pins excluded), in a stable order; pairs: (in_pin, out_pin) couples to
    put in one tile -- a module that copies the in-pin to the out-pin then
    wires them locally, whatever the static design wants.  Pins are spread
    evenly over ``partpin_tiles`` at no more than ``per_tile`` a tile
    (Vivado's own target is PARTPIN_SPREADING, default 5).  Raises
    ValueError when the region cannot take the pins.

    Measured (README "Pin placement"): in a 4-column, 3-row region a plan of
    at most 4 a tile routed 12 of 16 modules, 5 of which failed there with
    Vivado's own pins; a plan of up to 8 a tile failed for crowding.  The
    solver does not count on a plan."""
    tiles = partpin_tiles(device, cols, rows, trim)
    names = list(pins)
    if len(set(names)) != len(names):
        raise ValueError("duplicate pin names")
    partner = {}
    for a, b in pairs:
        if a not in partner and b not in partner and a != b:
            partner[a], partner[b] = b, a
    if per_tile < 2 and partner:
        raise ValueError("a pin plan with pairs needs per_tile >= 2")
    if len(names) > per_tile * len(tiles):
        raise ValueError("%d pins exceed %d tiles x %d" % (len(names), len(tiles),
                                                           per_tile))
    groups, seen = [], set()
    for p in names:
        if p in seen:
            continue
        g = [p, partner[p]] if p in partner and partner[p] in names else [p]
        seen.update(g)
        groups.append(g)
    step = len(tiles) / float(len(names))
    load = [0] * len(tiles)
    plan, k = [], 0.0
    for g in groups:
        t = int(k) % len(tiles)
        for _ in range(len(tiles)):
            if load[t] + len(g) <= per_tile:
                break
            t = (t + 1) % len(tiles)
        else:
            raise ValueError("no tile left for %s" % g)
        load[t] += len(g)
        plan.extend((p, tiles[t]) for p in g)
        k += len(g) * step
    return plan


def partpin_cut_demand(plan, pairs):
    """The cut demand a fixed pin plan implies, by direction.  ``pairs`` are
    (source pin, destination pin) couples whose module route runs from the
    first to the second -- a slot's in-pin to its out-pin.  Interconnect
    wires are one-way, so a pair whose destination lies north of a
    horizontal cut line and whose source lies south of it needs a wire that
    crosses the line going north (and so on for the other directions); each
    pair's route is its own net, so the counts are lower bounds on the
    wires the module needs, exact from the plan.  Returns
    {"north", "south", "east", "west": the most pairs forced across one cut
    line in that direction, "horizontal": {y: (north, south)} for every
    horizontal cut line between rows y and y + 1 that any pair crosses,
    "vertical": {x: (east, west)} likewise}.  A plan from ``partpin_plan``
    puts each pair in one tile, so every count is 0."""
    loc = dict(plan)

    def xy(tile):
        x, y = tile.split("_X")[1].split("Y")
        return int(x), int(y)

    hor, ver = {}, {}
    for a, b in pairs:
        if a not in loc or b not in loc:
            continue
        (xa, ya), (xb, yb) = xy(loc[a]), xy(loc[b])
        for y in range(min(ya, yb), max(ya, yb)):
            n, s_ = hor.get(y, (0, 0))
            hor[y] = (n + 1, s_) if yb > ya else (n, s_ + 1)
        for x in range(min(xa, xb), max(xa, xb)):
            e, w = ver.get(x, (0, 0))
            ver[x] = (e + 1, w) if xb > xa else (e, w + 1)
    return {"north": max([v[0] for v in hor.values()] or [0]),
            "south": max([v[1] for v in hor.values()] or [0]),
            "east": max([v[0] for v in ver.values()] or [0]),
            "west": max([v[1] for v in ver.values()] or [0]),
            "horizontal": hor, "vertical": ver}


def partpin_cut_check(device, plan, pairs, cols, rows):
    """Check a fixed pin plan's cut demand against the region's one-way
    capacity (device model ``routing.one_way_crossings_per_tile``).  At a
    horizontal cut line of a region with c module-routable interconnect
    columns, N pairs forced north and S south fit only if
    max(N - north*c, 0) + max(S - south*c, 0) <= vertical_either*c: the
    one-way wires of each direction, plus the long lines, which either
    direction can use but each only once.  Vertical cut lines likewise with
    east / west / horizontal_either per interconnect row.  Returns the
    violations, [(kind, line, forward, backward, capacity text)]; [] when the
    plan's forced demand fits."""
    rt = device.raw["routing"]
    ow = rt["one_way_crossings_per_tile"]
    types = rt["module_routing_types"]
    c = sum(1 for x in cols if device.col_type(x) in types)
    h = rt["int_tiles_per_cell"] * len(rows)
    d = partpin_cut_demand(plan, pairs)
    bad = []
    for kind, table, k, fwd, bwd, either in (
            ("horizontal", d["horizontal"], c, ow["north"], ow["south"], ow["vertical_either"]),
            ("vertical", d["vertical"], h, ow["east"], ow["west"], ow["horizontal_either"])):
        for line, (f, b) in sorted(table.items()):
            if max(f - fwd * k, 0) + max(b - bwd * k, 0) > either * k:
                bad.append((kind, line, f, b, "%d + %d one-way, %d either way"
                            % (fwd * k, bwd * k, either * k)))
    return bad


def partpin_xdc(cell, plan):
    """XDC lines placing ``plan``'s pins of hierarchical ``cell``."""
    return ["set_property HD.PARTPIN_LOCS %s [get_pins {%s/%s}]" % (t, cell, p)
            for p, t in plan]
