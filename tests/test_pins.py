"""Partition-pin routability: the optional ``pins`` and ``passthrough``
demands (milp.PIN_AREA_DENSITY, PIN_CUT_DENSITY, PIN_PACKING; README
"Partition pins").

MEASURED is every region built on the real part (xc7z020, Vivado 2019.1)
with Vivado placing the partition pins, for four RFP designs.  A region
"routed" when every module built in it routed, and "failed" when at least
one did not, attributed to the region and to a mechanism by the location of
the overlapping nodes: "area" (collisions among crowded pins) or "width"
(vertical wires across the middle rows).  "pred" marks a region whose
verdict was predicted and recorded before it was built.

The calibrated densities are the fit rule applied to this table: for each
limit, the densest routed region below the least-dense failure of that
limit's mechanism.  So no measured failure is accepted, and the regions that
routed above a constant are listed (SAFE_MISSES) rather than hidden."""
import pytest

# pins, pass-through (the most of any module): port bits of the region,
# output bits taken from an input pin (copied or computed)
DESIGNS = {
    "ga_b666": (1596, 648),       # RFP GA, 33 modules
    "ga_b445": (2050, 809),       # RFP GA, 46 modules
    "sobel_b200": (1472, 586),    # RFP sobel, 13 modules
    "lenet_b3000": (1325, 133),   # RFP LeNet, 5 modules
}
GA_PINS, GA_PASS = DESIGNS["ga_b666"]
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
]
# routed, and rejected by the calibrated constants (a conservative miss)
SAFE_MISSES = [
    ('ga_b666', 38, 43, [1, 2]),
    ('ga_b666', 30, 35, [1, 2]),
    ('ga_b666', 38, 43, [0, 1, 2]),
    ('ga_b666', 58, 63, [0, 1, 2]),
    ('ga_b445', 38, 43, [1, 2]),
    ('ga_b445', 28, 35, [0, 1]),
    ('sobel_b200', 22, 25, [0, 1, 2]),
]


def margins(fp, dev, design, c0, c1, rows, **kw):
    pins, t = DESIGNS[design]
    return fp.milp.pin_capacity(dev, list(range(c0, c1 + 1)), rows, pins, t, **kw)


def accepted(r):
    return min(r["area_margin"], r["width_margin"],
               r["height_margin"]) >= 1 - 1e-9


def densities(fp, dev, x):
    r = margins(fp, dev, *x[:4])
    return (fp.milp.PIN_AREA_DENSITY / r["area_margin"],
            fp.milp.PIN_CUT_DENSITY / r["width_margin"])


@pytest.mark.parametrize("x", [x for x in MEASURED if x[4] == "failed"],
                         ids=lambda x: "%s-%d-%d-%s" % (x[0], x[1], x[2], x[3]))
def test_no_measured_failure_is_accepted(fp, dev, x):
    assert not accepted(margins(fp, dev, *x[:4]))


def test_accepted_regions_routed_and_misses_listed(fp, dev):
    rejected = [x[:4] for x in MEASURED
                if x[4] == "routed" and not accepted(margins(fp, dev, *x[:4]))]
    assert sorted(rejected) == sorted(SAFE_MISSES)


def test_each_failure_is_rejected_by_its_own_limit(fp, dev):
    for x in MEASURED:
        if x[4] == "failed":
            r = margins(fp, dev, *x[:4])
            key = "area_margin" if x[5] == "area" else "width_margin"
            assert r[key] < 1, x


def test_constants_are_the_fit(fp, dev):
    for k, lim in ((0, "area"), (1, "width")):
        bad = min(densities(fp, dev, x)[k] for x in MEASURED
                  if x[4] == "failed" and x[5] == lim)
        ok = max(d for d in (densities(fp, dev, x)[k] for x in MEASURED
                             if x[4] == "routed") if d < bad - 1e-9)
        const = fp.milp.PIN_AREA_DENSITY if k == 0 else fp.milp.PIN_CUT_DENSITY
        assert abs(ok - const) < 1e-9 * const, lim


def test_every_design_has_predicted_regions(fp, dev):
    for design in DESIGNS:
        assert any(x[0] == design and x[6] == "pred" for x in MEASURED)


def test_solver_matches_pin_capacity_across_a_special(fp, dev):
    """The packed-band case is exact where pin columns and routing columns
    differ: a region over x=33 (column 32 takes no pins but routes) is
    feasible at its own width density and not below it."""
    keep = set((c, r) for c in range(28, 36) for r in range(3)) | {(25, 0), (22, 0)}
    forbid = [(c, r) for c in dev.xs for r in range(dev.nrows) if (c, r) not in keep]
    r = fp.milp.pin_capacity(dev, list(range(28, 36)), [0, 1, 2], GA_PINS, GA_PASS)
    dens = fp.milp.PIN_CUT_DENSITY / r["width_margin"]
    d = {"rp0": {"lut": 0, "ff": 0, "bram": 0, "dsp": 0, "slices": 100,
                 "pins": GA_PINS, "passthrough": GA_PASS}}
    fp.milp.solve(dev, d, objective="wr", forbid_cells=forbid,
                  pin_cut_density=1.001 * dens)
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, d, objective="wr", forbid_cells=forbid,
                      pin_cut_density=0.999 * dens)


def test_height_limit(fp, dev):
    """The horizontal counterpart: a 1-row region at its area capacity with
    the worst-case pass-through is bound by it once it is wider than
    sqrt(WIDTH x 124 / (8 x AREA)) routing columns (49 on xc7z020)."""
    m = fp.milp
    rt = dev.raw["routing"]
    wmax = (m.PIN_CUT_DENSITY * rt["horizontal_crossings_per_tile"]
            / (rt["pploc_wires_per_tile"] / 2 * m.PIN_AREA_DENSITY)) ** 0.5
    for n, ok in ((int(wmax) - 3, True), (int(wmax) + 3, False)):
        cols = []
        for c in dev.xs:
            cols.append(c)
            if sum(dev.col_type(x) in rt["module_routing_types"]
                   for x in cols) == n:
                break
        cap = m.pin_capacity(dev, cols, [0], 1)["area_capacity"]
        r = m.pin_capacity(dev, cols, [0], int(cap))
        assert r["cols"] == n and (r["height_margin"] >= 1) == ok


def fits(fp, dev, cols, rows, pins=GA_PINS, t=GA_PASS):
    return accepted(fp.milp.pin_capacity(dev, list(cols), rows, pins, t))


def test_device_routing_facts(dev):
    rt = dev.raw["routing"]
    assert rt["pploc_wires_per_tile"] == 16          # EL1/ER1/WL1/WR1 x 4
    assert rt["vertical_crossings_per_tile"] == 196
    assert rt["int_tiles_per_cell"] == 50
    assert "OTHER30" not in rt["module_routing_types"]


def test_special_column_interconnect_does_not_count(fp, dev):
    # tiles 30..35 cover the clock-spine column 33: its interconnect stays
    # static, so the region has 5 module-routable columns, not 6
    r = fp.milp.pin_capacity(dev, list(range(30, 36)), [1], GA_PINS)
    assert (r["tiles"], r["cols"]) == (250, 5)
    # ... and column 32, which Vivado prohibits while a region covers x=33
    # (special_splits), takes no pins
    assert r["pploc_cols"] == 4
    # a BRAM and a DSP column's interconnect do count
    r = fp.milp.pin_capacity(dev, list(range(56, 62)), [0], GA_PINS)
    assert (r["tiles"], r["cols"], r["pploc_cols"]) == (300, 6, 6)


def test_band(fp, dev):
    # the pins spread over the region's height, or over the rows their
    # pin columns fill at PIN_PACKING per tile when that is shorter
    pack = lambda ncols: GA_PINS / (fp.milp.PIN_PACKING * ncols)
    band = lambda cols, rows: fp.milp.pin_capacity(dev, list(cols), rows,
                                                   GA_PINS)["band"]
    assert band(range(30, 36), [1, 2]) == 100              # 2 rows < pack(4)
    assert abs(band(range(30, 36), [0, 1, 2]) - pack(4)) < 1e-9
    assert abs(band(range(38, 44), [0, 1, 2]) - pack(6)) < 1e-9


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


def test_without_pins_wr_picks_a_region_too_narrow(fp, dev):
    """GA's demand without pins: the wasted-resources optimum is the 8 slice
    column x 3 row region that failed routing on the real part."""
    res = fp.milp.solve(dev, demands(), objective="wr")
    assert any(not fits(fp, dev, r["cols"], r["rows"])
               for r in res["regions"].values())


@pytest.mark.parametrize("objective", ["wr", "frames"])
def test_pins_limits_hold(fp, dev, objective):
    res = fp.milp.solve(dev, demands(pins=GA_PINS, passthrough=GA_PASS), objective=objective)
    for r in res["regions"].values():
        assert r["pins"] == GA_PINS
        assert r["pin_area_margin"] >= 1 - 1e-9
        assert r["pin_width_margin"] >= 1 - 1e-9
        assert fits(fp, dev, r["cols"], r["rows"])
        assert r["pin_cols"] >= 5


def test_densities_are_parameters(fp, dev):
    res = fp.milp.solve(dev, demands(pins=GA_PINS, passthrough=GA_PASS), objective="wr",
                        pin_cut_density=0.5 * fp.milp.PIN_CUT_DENSITY)
    half = 0.5 * fp.milp.PIN_CUT_DENSITY
    for r in res["regions"].values():
        assert r["pin_width_margin"] >= 1 - 1e-9
        assert fp.milp.pin_capacity(dev, r["cols"], r["rows"], GA_PINS,
                                    pin_cut_density=half)["width_margin"] \
            >= 1 - 1e-9
    # the default-density optimum does not survive the halved density
    base = fp.milp.solve(dev, demands(pins=GA_PINS, passthrough=GA_PASS), objective="wr")
    assert any(fp.milp.pin_capacity(dev, r["cols"], r["rows"], GA_PINS,
                                    pin_cut_density=half)["width_margin"] < 1
               for r in base["regions"].values())


def test_too_many_pins_is_infeasible(fp, dev):
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, demands(pins=40000), objective="wr")


def test_pins_need_the_routing_section(fp, dev):
    raw = dict(dev.raw)
    raw.pop("routing")
    bare = fp.device.Device(raw)
    fp.milp.solve(bare, demands(), objective="wr")          # fine without pins
    with pytest.raises(ValueError):
        fp.milp.solve(bare, demands(pins=GA_PINS, passthrough=GA_PASS), objective="wr")


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
