"""The floorplanning MILP, solved with HiGHS (via highspy, MIT-licensed).

The formulation follows the published FLORA model (Seyoum, Biondi, Buttazzo,
CODES+ISSS 2019): axis-aligned rectangles on (column, clock-region-row) axes,
per-type resource coverage constraints, region no-overlap, forbidden cells,
back-to-back interconnect-pair legality, full-clock-region height.  It is
RESTATED in an equivalent encoding -- column-cover binaries instead of
coordinate variables with fingerprint macro-ranges -- which at device scale
(tens of columns x a few rows) solves in seconds and makes per-cell frame
costs exact rather than fingerprint-approximated.  Two extensions:

  * a static BRAM reservation: covered BRAM is capped so the static design
    keeps at least the amount it needs (a rectangle static region would be
    wrong -- static logic legitimately occupies everything outside the RPs);
  * objective "frames": minimize total configuration frames of the partial
    bitstreams (measured frame accounting, ``frames.py``), the quantity
    proportional to partial size and reconfiguration time;
  * a SLICE-occupancy demand (measured failure, Vivado [Place 30-487]):
    LUT/FF coverage alone under-models slice packing.  A slice holds only
    one unique control set, so control-set-rich modules occupy far more
    slices than their LUT count suggests -- the case study's round-2
    build (2026-07-16) failed detail placement with the region at 72 % LUT
    / 28 % FF utilization because its 33-control-set module needed ~930
    slices against the pblock's 900.  Each region therefore also carries a
    ``slices`` demand covered by CLB cells (per_cell["slices"] each, with
    derate * headroom applied like every other resource).  When a demand
    omits ``slices`` it defaults to ceil(lut/4) -- the perfect-packing
    floor (4 LUTs/slice), which the measured failure shows is OPTIMISTIC:
    measure occupied slices from a routed design instead
    (report_utilization -pblocks on the routed checkpoint, "Slice" row);
  * edge alignment (measured failure, Vivado [Constraints 18-993]): a
    site-less special column may not be the first or last covered column
    of a region.  Pblocks are realized as SITE ranges; a special column
    contributes no sites, so covering it at a region edge silently
    retracts the physical pblock edge into the neighboring site-bearing
    column -- splitting that column's back-to-back interconnect pair
    against static.  Vivado then prohibits placement in BOTH columns of
    the split pair ([Constraints 18-993]/[18-996]/[18-992]: 100 SLICEL
    sites confiscated per edge on xc7z020), which is how the case
    study's first hardware build failed placement (2026-07-16: rp1 needed
    3,005 LUTs on the 2,800 that survived the exclusion, 107.3 %).  With
    specials forced interior, edge columns carry sites and the pair
    constraints guarantee both emitted x-edges land on pair boundaries.

Objective "wr" is FLORA's wasted-resources metric (their eq. 3) with weights
nu_t = 1/T_t (T_t = device total of type t) and the wirelength term dropped
(a = 0, b = 1), exactly as FLORA's own Pynq case study was configured.
Constant demand offsets are dropped (argmin-equivalent).

Encoding (regions i; columns c = tile-name X; clock-region rows r):
  cov[i][c] in {0,1}   region i covers column c
  st[i][c]  in {0,1}   start indicator: sum_c st == 1 and st >= cov_c -
                       cov_{c-1}  ->  exactly one 0->1 transition  ->
                       a contiguous, nonempty column span
  row[i][r], rst[i][r] the same for rows (vertical contiguity; full
                       clock-region height is implicit in the row axis)
  w[i][c][r] = cov AND row (linearized)  ->  covered cells
  hb[i][r]  >= w[i][c][r] for BRAM c     ->  BRAM-content pad accounting
Constraints:
  * w[i][c][r] == 0 and cov+row <= 1 where column c has no fabric at row r
    (processor-subsystem occlusion etc. -- forbidden cells)
  * interconnect pairs: cov[i][2k] == cov[i][2k+1] on any covered row where
    the pair is back-to-back (measured per-row pair map in the device model)
  * resources: derate * capacity(covered cells) >= demand, per type
  * no-overlap: sum_i w[i][c][r] <= 1 per cell
  * static BRAM reservation: covered RAMB18 <= device total - reserve

All BRAM quantities in demands and the reservation are in RAMB18 (18 Kb
half-block) units; one RAMB36 = two RAMB18.
"""
import time

import highspy

from . import frames as _frames
from . import emit as _emit

DEMAND_KEYS = ("lut", "ff", "bram", "dsp", "slices")


def slice_demand(d):
    """The slice demand of one region's demand dict.

    Explicit ``slices`` (measured occupied slices of a routed design) when
    present; otherwise ceil(lut/4), the perfect-packing floor.  The default
    is documented-optimistic: 4 LUTs/slice assumes every slice fills, but a
    slice holds only one unique control set, and the case study's measured
    round-2 placement failure ([Place 30-487]) sat at 2.8 LUTs/slice
    minimum (2,601 LUTs needing ~930 slices) -- 2.35 LUTs/slice as routed.
    """
    if "slices" in d and d["slices"] is not None:
        return d["slices"]
    return -(-d.get("lut", 0) // 4)


def solve(device, demands, objective="frames", derate=1.0, headroom=0.93,
          forbid_specials=False, static_bram_reserve=0, verbose=False):
    """Floorplan the regions in ``demands`` on ``device``.

    demands: dict name -> {"lut": int, "ff": int, "bram": int, "dsp": int
             [, "slices": int]} (bram in RAMB18 units; slices = measured
             occupied slices, defaulting to the optimistic ceil(lut/4)
             floor when absent -- see ``slice_demand``).
    objective: "frames" (minimize total configuration frames) or
               "wr" (FLORA wasted-resources, nu_t = 1/T_t).
    derate: usable fraction of covered capacity (the user's design-margin
            knob, e.g. 0.5 = 2x headroom); constraints are
            derate * headroom * capacity >= demand.
    headroom: calibrated placement-headroom fraction, multiplied with
            derate.  Distinct from derate: headroom absorbs what the flow
            itself eats between the demand snapshot and a placed design.
            Default 0.93, calibrated on the case study's first hardware
            build (2026-07-16): rp1 synthesized to 3,005 LUTs against the
            2,972 modeled from the previous build's post-route reports
            (+1.1 % netlist growth), and the placer additionally needs
            slack to commit carry-chain/wide-mux shapes -- it failed
            outright at 107.3 % post-exclusion demand, so the honest
            packing ceiling sits below 93 %.
    forbid_specials: exclude resource-less special columns (clock spine /
            config columns) from all regions.
    static_bram_reserve: RAMB18 that must remain outside all regions.
    Returns a result dict (see below); raises RuntimeError if the model is
    not solved to proven optimality.
    """
    regions = list(demands.keys())
    xs = device.xs
    nrows = device.nrows
    pc = device.per_cell
    cols = device.columns

    h = highspy.Highs()
    if not verbose:
        h.silent()

    cov = {i: {} for i in regions}
    st = {i: {} for i in regions}
    row = {i: {} for i in regions}
    rst = {i: {} for i in regions}
    w = {i: {} for i in regions}
    hb = {i: {} for i in regions}
    for i in regions:
        for c in xs:
            cov[i][c] = h.addBinary()
            st[i][c] = h.addBinary()
        for r in range(nrows):
            row[i][r] = h.addBinary()
            rst[i][r] = h.addBinary()
            hb[i][r] = h.addBinary()
        for c in xs:
            for r in range(nrows):
                w[i][(c, r)] = h.addBinary()

    for i in regions:
        if forbid_specials:
            for c in xs:
                if cols[c]["type"] == "OTHER30":
                    h.addConstr(cov[i][c] == 0)
        # horizontal contiguity: exactly one 0->1 transition
        prev = None
        for c in xs:
            if prev is None:
                h.addConstr(st[i][c] >= cov[i][c])
            else:
                h.addConstr(st[i][c] >= cov[i][c] - cov[i][prev])
            prev = c
        h.addConstr(sum(st[i][c] for c in xs) == 1)
        # vertical contiguity
        for r in range(nrows):
            if r == 0:
                h.addConstr(rst[i][r] >= row[i][r])
            else:
                h.addConstr(rst[i][r] >= row[i][r] - row[i][r - 1])
        h.addConstr(sum(rst[i][r] for r in range(nrows)) == 1)
        # w = cov AND row; forbidden cells
        for c in xs:
            for r in range(nrows):
                if device.cell_ok(c, r):
                    h.addConstr(w[i][(c, r)] <= cov[i][c])
                    h.addConstr(w[i][(c, r)] <= row[i][r])
                    h.addConstr(w[i][(c, r)] >= cov[i][c] + row[i][r] - 1)
                else:
                    h.addConstr(w[i][(c, r)] == 0)
                    # a region may not span a dead cell at all:
                    h.addConstr(cov[i][c] + row[i][r] <= 1)
        # interconnect pairs (measured per-row pair map)
        for x, prows in device.pairs.items():
            if x in cols and (x + 1) in cols:
                for r in prows:
                    h.addConstr(cov[i][x] - cov[i][x + 1] <= 1 - row[i][r])
                    h.addConstr(cov[i][x + 1] - cov[i][x] <= 1 - row[i][r])
        # edge alignment ([Constraints 18-993]): a site-less special
        # column (OTHER30) may not be the first or last covered column.
        # Site ranges cannot express covering it at an edge, so the
        # physical pblock edge retracts into the neighboring site-bearing
        # column, mid-pair (see module docstring for the measured failure).
        # cov[c] <= cov[neighbor] reads: "if c is covered, so is its
        # neighbor on that side" -- i.e. c is never the span's endpoint.
        for k, c in enumerate(xs):
            if cols[c]["type"] != "OTHER30":
                continue
            if k == 0 or k == len(xs) - 1:
                h.addConstr(cov[i][c] == 0)
                continue
            h.addConstr(cov[i][c] <= cov[i][xs[k - 1]])
            h.addConstr(cov[i][c] <= cov[i][xs[k + 1]])
        # resources (usable = derate * headroom * capacity)
        d = demands[i]
        usable = derate * headroom

        def cap(per_cell_amount, col_type):
            return sum(per_cell_amount * w[i][(c, r)] for c in xs
                       for r in range(nrows)
                       if cols[c]["type"] == col_type and device.cell_ok(c, r))

        h.addConstr(usable * cap(pc["lut"], "CLB") >= d.get("lut", 0))
        h.addConstr(usable * cap(pc["ff"], "CLB") >= d.get("ff", 0))
        h.addConstr(usable * cap(pc["dsp"], "DSP") >= d.get("dsp", 0))
        h.addConstr(usable * cap(pc["ramb18"], "BRAM") >= d.get("bram", 0))
        # slice occupancy ([Place 30-487], measured round-2 failure):
        # control sets pin FF packing (one unique control set per slice),
        # so slices bind before LUTs on control-set-rich modules.
        h.addConstr(usable * cap(pc["slices"], "CLB") >= slice_demand(d))
        # hb: BRAM presence per row (content-pad accounting)
        for c in xs:
            if cols[c]["type"] == "BRAM":
                for r in range(nrows):
                    if device.cell_ok(c, r):
                        h.addConstr(hb[i][r] >= w[i][(c, r)])

    # no-overlap
    for c in xs:
        for r in range(nrows):
            h.addConstr(sum(w[i][(c, r)] for i in regions) <= 1)

    # static BRAM reservation (RAMB18 units)
    if static_bram_reserve:
        covered_b18 = sum(pc["ramb18"] * w[i][(c, r)] for i in regions
                          for c in xs for r in range(nrows)
                          if cols[c]["type"] == "BRAM" and device.cell_ok(c, r))
        h.addConstr(covered_b18 <= device.total_ramb18() - static_bram_reserve)

    # objective
    def frames_expr(i):
        # covered frames + pads, both doubled; the fixed preamble is a
        # constant and is added back in the reported per-region totals.
        e = 0
        for c in xs:
            fc = device.frames[cols[c]["type"]]
            for r in range(nrows):
                if device.cell_ok(c, r):
                    e = e + 2 * fc * w[i][(c, r)]
                    if cols[c]["type"] == "BRAM":
                        e = e + 2 * device.bram_content_frames * w[i][(c, r)]
        e = e + sum(2 * row[i][r] for r in range(nrows))
        e = e + sum(2 * hb[i][r] for r in range(nrows))
        return e

    if objective == "frames":
        h.minimize(sum(frames_expr(i) for i in regions))
    elif objective == "wr":
        T = device.totals
        obj = 0
        for i in regions:
            for c in xs:
                for r in range(nrows):
                    if not device.cell_ok(c, r):
                        continue
                    t = cols[c]["type"]
                    if t == "CLB":
                        obj = obj + (pc["slices"] / T["slices"]) * w[i][(c, r)]
                    elif t == "BRAM":
                        obj = obj + (pc["ramb36"] / T["ramb36"]) * w[i][(c, r)]
                    elif t == "DSP":
                        obj = obj + (pc["dsp"] / T["dsp"]) * w[i][(c, r)]
        h.minimize(obj)
    else:
        raise ValueError("unknown objective %r" % (objective,))

    t0 = time.time()
    h.run()
    dt = time.time() - t0
    status = h.getModelStatus()
    if status != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError("MILP not solved to optimality: %s" % (status,))
    sol = h.getSolution().col_value

    def val(v):
        return sol[v.index]

    out = {"objective": objective, "derate": derate, "headroom": headroom,
           "forbid_specials": bool(forbid_specials),
           "static_bram_reserve": static_bram_reserve,
           "status": str(status), "solve_seconds": dt, "regions": {}}
    T = device.totals
    for i in regions:
        ccols = [c for c in xs if val(cov[i][c]) > 0.5]
        rrows = [r for r in range(nrows) if val(row[i][r]) > 0.5]
        nframes, nbytes = _frames.region_frames(device, ccols, rrows)
        cells = [(c, r) for c in ccols for r in rrows]
        wr = 0.0
        for c, r in cells:
            t = cols[c]["type"]
            if t == "CLB":
                wr += pc["slices"] / T["slices"]
            elif t == "BRAM":
                wr += pc["ramb36"] / T["ramb36"]
            elif t == "DSP":
                wr += pc["dsp"] / T["dsp"]
        out["regions"][i] = {
            "cols": ccols, "rows": rrows,
            "lut": sum(pc["lut"] for c, r in cells if cols[c]["type"] == "CLB"),
            "ff": sum(pc["ff"] for c, r in cells if cols[c]["type"] == "CLB"),
            "slices": sum(pc["slices"] for c, r in cells
                          if cols[c]["type"] == "CLB"),
            "slices_demand": slice_demand(demands[i]),
            "slices_demand_derived": "slices" not in demands[i]
                                     or demands[i]["slices"] is None,
            "dsp": sum(pc["dsp"] for c, r in cells if cols[c]["type"] == "DSP"),
            "bram_ramb18": sum(pc["ramb18"] for c, r in cells
                               if cols[c]["type"] == "BRAM"),
            "wr_covered": wr,
            "frames": nframes, "bytes": nbytes,
            "ranges": _emit.site_ranges(device, ccols, rrows),
        }
    return out
