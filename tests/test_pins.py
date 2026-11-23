"""Partition-pin sites: the optional ``pins`` demand (``pin_headroom``,
default milp.PIN_HEADROOM = 1, the exact bound; milp.PIN_HEADROOM_MEASURED_42,
the measured value a caller may pass; README "Partition pins").

The constraint is exact at pin_headroom 1 (one pin per routing node of the
region's module-routable interconnect tiles).
MEASURED is every region built on the real part (xc7z020, Vivado 2019.1)
with Vivado placing the partition pins, for four RFP designs.  A region
"routed" when every module built in it routed, and "failed" when at least
one did not, attributed to the region and to a mechanism by the location of
the overlapping nodes: "area" (collisions among crowded pins) or "width"
(vertical wires across the middle rows; not modeled).  "pred" marks a
region whose verdict was predicted and recorded before it was built (under
the model of the time).

PIN_HEADROOM_MEASURED_42 is the fit rule over this table: the densest routed region
below the least-dense area failure.  No area failure is accepted.  The width
failures are accepted (the model does not cover them: docs/LIMITS.md) and
listed in ACCEPTED_FAILURES; the routed regions that headroom rejects are
listed in SAFE_MISSES.  At the default (exact) headroom every measured
region is accepted."""
import pytest

# partition pins: port bits of the region, clock excluded
DESIGNS = {
    "ga_b666": 1596,       # RFP GA, 33 modules
    "ga_b445": 2050,       # RFP GA, 46 modules
    "sobel_b200": 1472,    # RFP sobel, 13 modules
    "lenet_b3000": 1325,   # RFP LeNet, 5 modules
}
GA_PINS = DESIGNS["ga_b666"]
GA = {"lut": 446, "ff": 1738, "bram": 0, "dsp": 0, "slices": 1000}

# (design, first and last interconnect column, rows, verdict, mechanism, when)
MEASURED = [
    ('ga_b666', 40, 51, [0], 'routed', '', 'calib'),   # ga_of2 s1000 rp0
    ('ga_b666', 26, 35, [1], 'routed', '', 'calib'),   # ga_of2 s750 rp0
    ('ga_b666', 26, 35, [0], 'routed', '', 'calib'),   # ga_of2 s750 rp1
    ('ga_b666', 28, 35, [0, 1, 2], 'routed', '', 'calib'),   # build B rp0
    ('ga_b666', 36, 43, [0, 1, 2], 'routed', '', 'calib'),   # build B rp1
    ('ga_b666', 38, 43, [1, 2], 'routed', '', 'calib'),   # build A rp1
    ('ga_b666', 30, 35, [1, 2], 'routed', '', 'calib'),   # build A rp0
    ('ga_b666', 52, 55, [0, 1, 2], 'failed', 'width', 'calib'),   # tall rp0 / r8x3 (rm_17,18,19,22)
    ('ga_b666', 26, 29, [0, 1, 2], 'failed', 'width', 'calib'),   # ga_of2 s1000 rp1 (rm_19, rm_22)
    ('ga_b666', 38, 41, [0, 1, 2], 'failed', 'width', 'calib'),   # tall rp1 / r8x3b (rm_19, 9 nets)
    ('ga_b666', 30, 35, [1], 'failed', 'area', 'calib'),   # r10x1 rp0 (7 x one pin collision)
    ('ga_b666', 30, 35, [0], 'failed', 'area', 'calib'),   # r10x1 rp1 (rm_19)
    ('ga_b666', 30, 35, [0, 1, 2], 'failed', 'width', 'pred'),   # V1 T3 (rm_27, 944 nets)
    ('ga_b666', 56, 61, [1, 2], 'failed', 'width', 'pred'),   # V1 T6 (rm_27, 20 signals)
    ('ga_b666', 56, 65, [1], 'routed', '', 'pred'),   # V2 T2
    ('ga_b666', 62, 71, [0], 'routed', '', 'pred'),   # V2 T4
    ('ga_b666', 38, 43, [0, 1, 2], 'routed', '', 'pred'),   # V3 rp0
    ('ga_b666', 58, 63, [0, 1, 2], 'routed', '', 'pred'),   # V3 rp1
    ('ga_b445', 38, 43, [1, 2], 'routed', '', 'pred'),   # G1 rp0 (predicted to fail, 0.96)
    ('ga_b445', 28, 35, [0, 1], 'routed', '', 'pred'),   # G1 rp1
    ('lenet_b3000', 22, 25, [0, 1, 2], 'routed', '', 'pred'),   # L1 rp0
    ('lenet_b3000', 58, 61, [0, 1, 2], 'routed', '', 'pred'),   # L1 rp1
    ('sobel_b200', 22, 25, [0, 1, 2], 'routed', '', 'pred'),   # So1 rp0 (predicted to fail)
    ('sobel_b200', 58, 61, [0, 1, 2], 'failed', 'width', 'pred'),   # So1 rp1 (rm_9 8 nets, rm_10 4; south-going verticals)
    ('lenet_b3000', 24, 31, [1], 'routed', '', 'pred'),   # L2 rp0 (held out: predicted ROUTES at the final constants)
    ('lenet_b3000', 58, 63, [1], 'routed', '', 'pred'),   # L2 rp1 (predicted to fail, area 0.80)
    ('sobel_b200', 24, 29, [1, 2], 'routed', '', 'pred'),   # So2 rp0 (held out: ROUTES, width 1.03)
    ('sobel_b200', 56, 65, [1], 'routed', '', 'pred'),   # So2 rp1 (held out: ROUTES)
    ('ga_b666', 36, 43, [1], 'routed', '', 'pred'),   # E3v rp0 (held out: ROUTES at area 1.11; E3 without its plan)
    ('ga_b666', 56, 63, [1], 'routed', '', 'pred'),   # E3v rp1 (held out)
    ('ga_b445', 28, 37, [1, 2], 'routed', '', 'pred'),   # G2 rp0 (held out: ROUTES at width 1.07)
    ('ga_b445', 52, 61, [0], 'failed', 'area', 'pred'),   # G2 rp1 (held out: ROUTES at area 1.08; rm_2 of 46 failed, 2 overlaps near pins)
    ('ga_b666', 38, 43, [0, 1], 'failed', 'width', 'pred'),   # S6a rp0 (rm_21, 19, 27, 13 of the 14 hardest; north-going)
    ('ga_b666', 58, 63, [1, 2], 'routed', '', 'pred'),   # S6a rp1 (14 hardest modules)
    ('ga_b666', 20, 25, [1, 2], 'routed', '', 'pred'),   # S6b rp0 (14 hardest modules)
    ('ga_b666', 66, 71, [1, 2], 'routed', '', 'pred'),   # S6b rp1 (14 hardest modules)
    ('ga_b666', 28, 35, [0, 1], 'routed', '', 'pred'),   # S7a rp0 (held out at the width constant; 14 hardest modules)
    ('ga_b666', 58, 63, [0, 1], 'routed', '', 'pred'),   # S7a rp1 (14 hardest modules)
    ('ga_b666', 30, 37, [1, 2], 'routed', '', 'pred'),   # S7b rp0 (held out at the width constant; 14 hardest modules)
    ('ga_b666', 60, 65, [1, 2], 'routed', '', 'pred'),   # S7b rp1 (14 hardest modules)
    ('ga_b666', 24, 29, [1, 2], 'failed', 'width', 'pred'),   # S6c rp0 (rm_13, 21, 19, 27 of the 14 hardest; north-going)
    ('ga_b666', 56, 61, [0, 1], 'routed', '', 'pred'),   # S6c rp1 (14 hardest modules)
]
# accepted by the default headroom, and failed (all width: not modeled)
ACCEPTED_FAILURES = [
    ('ga_b666', 52, 55, [0, 1, 2]),
    ('ga_b666', 26, 29, [0, 1, 2]),
    ('ga_b666', 38, 41, [0, 1, 2]),
    ('ga_b666', 30, 35, [0, 1, 2]),
    ('ga_b666', 56, 61, [1, 2]),
    ('sobel_b200', 58, 61, [0, 1, 2]),
    ('ga_b666', 38, 43, [0, 1]),
    ('ga_b666', 24, 29, [1, 2]),
]
# routed, and rejected by the default headroom (a conservative miss)
SAFE_MISSES = [
    ('lenet_b3000', 58, 63, [1]),
]


def cap(fp, dev, design, c0, c1, rows, **kw):
    """The site check at the measured headroom, unless one is given."""
    kw.setdefault("pin_headroom", fp.milp.PIN_HEADROOM_MEASURED_42)
    return fp.milp.pin_capacity(dev, list(range(c0, c1 + 1)), rows,
                                DESIGNS[design], **kw)


def accepted(r):
    return r["margin"] >= 1 - 1e-9


def use(fp, dev, x):
    """Pins per partition-pin site of a measured region."""
    r = cap(fp, dev, *x[:4])
    return DESIGNS[x[0]] / r["sites"]


@pytest.mark.parametrize("x", [x for x in MEASURED if x[5] == "area"],
                         ids=lambda x: "%s-%d-%d-%s" % (x[0], x[1], x[2], x[3]))
def test_no_area_failure_is_accepted(fp, dev, x):
    assert not accepted(cap(fp, dev, *x[:4]))


def test_classification_is_recorded(fp, dev):
    acc_fail = [x[:4] for x in MEASURED
                if x[4] == "failed" and accepted(cap(fp, dev, *x[:4]))]
    miss = [x[:4] for x in MEASURED
            if x[4] == "routed" and not accepted(cap(fp, dev, *x[:4]))]
    assert sorted(acc_fail) == sorted(ACCEPTED_FAILURES)
    assert sorted(miss) == sorted(SAFE_MISSES)
    assert all(x[5] == "width" for x in MEASURED if x[:4] in ACCEPTED_FAILURES)


def test_headroom_is_the_fit(fp, dev):
    bad = min(use(fp, dev, x) for x in MEASURED if x[5] == "area")
    ok = max(u for u in (use(fp, dev, x) for x in MEASURED if x[4] == "routed")
             if u < bad - 1e-12)
    assert abs(ok - fp.milp.PIN_HEADROOM_MEASURED_42) < 1e-12


def test_default_is_exact(fp, dev):
    """The default pin headroom is the exact bound, not a calibration: a
    region with one pin per routing node is feasible without passing a
    headroom, and one more pin is not.  Every measured region, routed or
    failed, is accepted at the default."""
    assert fp.milp.PIN_HEADROOM == 1.0
    keep = set((c, 1) for c in range(40, 44)) | {(25, 0), (22, 0)}
    forbid = [(c, r) for c in dev.xs for r in range(dev.nrows) if (c, r) not in keep]
    sites = fp.milp.pin_capacity(dev, list(range(40, 44)), [1], 1)["sites"]
    d = {"lut": 0, "ff": 0, "bram": 0, "dsp": 0, "slices": 100}
    fp.milp.solve(dev, {"rp0": dict(d, pins=sites)}, objective="wr",
                  forbid_cells=forbid)
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, {"rp0": dict(d, pins=sites + 1)}, objective="wr",
                      forbid_cells=forbid)
    assert all(accepted(cap(fp, dev, *x[:4], pin_headroom=None)) for x in MEASURED)


def test_exact_bound_at_headroom_one(fp, dev):
    """At pin_headroom 1 the constraint is the exact site count: a region
    with exactly one pin per routing node is feasible, one more pin is not."""
    keep = set((c, 1) for c in range(40, 44)) | {(25, 0), (22, 0)}
    forbid = [(c, r) for c in dev.xs for r in range(dev.nrows) if (c, r) not in keep]
    sites = fp.milp.pin_capacity(dev, list(range(40, 44)), [1], 1)["sites"]
    assert sites == 4 * 50 * dev.raw["routing"]["wires_per_tile"]
    d = {"lut": 0, "ff": 0, "bram": 0, "dsp": 0, "slices": 100}
    fp.milp.solve(dev, {"rp0": dict(d, pins=sites)}, objective="wr",
                  forbid_cells=forbid, pin_headroom=1.0)
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, {"rp0": dict(d, pins=sites + 1)}, objective="wr",
                      forbid_cells=forbid, pin_headroom=1.0)


def test_every_design_has_predicted_regions(fp, dev):
    for design in DESIGNS:
        assert any(x[0] == design and x[6] == "pred" for x in MEASURED)


def test_device_routing_facts(dev):
    rt = dev.raw["routing"]
    assert rt["wires_per_tile"] == 99                # routing nodes: the pin sites
    assert rt["pploc_wires_per_tile"] == 16          # EL1/ER1/WL1/WR1 x 4
    assert rt["vertical_crossings_per_tile"] == 196
    assert rt["int_tiles_per_cell"] == 50
    assert "OTHER30" not in rt["module_routing_types"]


def test_special_column_interconnect_does_not_count(fp, dev):
    # tiles 30..35 cover the clock-spine column 33: its interconnect stays
    # static, so the region has 5 module-routable columns, not 6
    r = fp.milp.pin_capacity(dev, list(range(30, 36)), [1], GA_PINS)
    assert (r["tiles"], r["cols"]) == (250, 5)
    # a BRAM and a DSP column's interconnect do count
    r = fp.milp.pin_capacity(dev, list(range(56, 62)), [0], GA_PINS)
    assert (r["tiles"], r["cols"]) == (300, 6)


def demands(**extra):
    return {"rp0": dict(GA, **extra), "rp1": dict(GA, **extra)}


def test_without_pins_no_pin_keys(fp, dev):
    res = fp.milp.solve(dev, demands(), objective="wr")
    for r in res["regions"].values():
        assert "pins" not in r and "pin_area_margin" not in r


def test_zero_pins_is_no_pins(fp, dev):
    a = fp.milp.solve(dev, demands(), objective="wr")
    b = fp.milp.solve(dev, demands(pins=0), objective="wr")
    strip = lambda res: {k: (v["cols"], v["rows"]) for k, v in res["regions"].items()}
    assert strip(a) == strip(b)


@pytest.mark.parametrize("objective", ["wr", "frames"])
def test_pins_limits_hold(fp, dev, objective):
    res = fp.milp.solve(dev, demands(pins=GA_PINS), objective=objective)
    for r in res["regions"].values():
        assert r["pins"] == GA_PINS
        assert r["pin_margin"] >= 1 - 1e-9
        assert accepted(fp.milp.pin_capacity(dev, r["cols"], r["rows"], GA_PINS))


def test_headroom_is_a_parameter(fp, dev):
    """A lower pin headroom needs more sites: at the measured headroom the
    optimum's regions do not all survive half of it, and the half-headroom
    solve's do."""
    full = fp.milp.PIN_HEADROOM_MEASURED_42
    half = 0.5 * full
    res = fp.milp.solve(dev, demands(pins=GA_PINS), objective="wr",
                        pin_headroom=half)
    for r in res["regions"].values():
        assert fp.milp.pin_capacity(dev, r["cols"], r["rows"], GA_PINS,
                                    pin_headroom=half)["margin"] >= 1 - 1e-9
    base = fp.milp.solve(dev, demands(pins=GA_PINS), objective="wr",
                         pin_headroom=full)
    assert any(fp.milp.pin_capacity(dev, r["cols"], r["rows"], GA_PINS,
                                    pin_headroom=half)["margin"] < 1
               for r in base["regions"].values())


def test_too_many_pins_is_infeasible(fp, dev):
    # more pins than the whole device has partition-pin sites: infeasible at
    # the exact bound; 40,000 is infeasible already at the measured headroom
    rt = dev.raw["routing"]
    cols = [c for c in dev.xs if dev.col_type(c) in rt["module_routing_types"]]
    every = fp.milp.pin_capacity(dev, cols, list(range(dev.nrows)), 1)["sites"]
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, demands(pins=every + 1), objective="wr")
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, demands(pins=40000), objective="wr",
                      pin_headroom=fp.milp.PIN_HEADROOM_MEASURED_42)


def test_pins_need_the_routing_section(fp, dev):
    raw = dict(dev.raw)
    raw.pop("routing")
    bare = fp.device.Device(raw)
    fp.milp.solve(bare, demands(), objective="wr")          # fine without pins
    with pytest.raises(ValueError):
        fp.milp.solve(bare, demands(pins=GA_PINS), objective="wr")


def test_csv_pins_column(fp, tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("name,lut,ff,bram,dsp,slices,pins\n"
                 "rp0,446,1738,0,0,1000,1596\nrp1,446,1738,0,0,1000,1596\n")
    d = fp.cli.read_demands_csv(str(p))
    assert d["rp0"]["pins"] == 1596 and d["rp1"]["slices"] == 1000
    p.write_text("rp0,446,1738,0,0,1000\n")
    assert "pins" not in fp.cli.read_demands_csv(str(p))["rp0"]
    p.write_text("rp0,446,1738,0,0,1000,-1\n")
    with pytest.raises(ValueError):
        fp.cli.read_demands_csv(str(p))
