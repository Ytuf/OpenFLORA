"""Partition-pin routability: the optional ``pins`` demand (milp.PIN_AREA_DENSITY,
PIN_CUT_DENSITY, PIN_PACKING; README "Partition pins").

The calibration design is RFP's GA at budget 666 (33 modules, 1,596 partition
pins per region, memory registers off) on xc7z020 with Vivado 2019.1.  Every
region below was built on the real part; it "routed" when all 33 modules
routed in it, and "failed" when at least one module failed there (attributed
to the region by the location of the overlapping nodes)."""
import pytest

GA_PINS = 1596
GA = {"lut": 446, "ff": 1738, "bram": 0, "dsp": 0, "slices": 1000}

# (interconnect columns, clock-region rows, routed?) -- measured
MEASURED = [
    (range(40, 52), [0], True),          # 22 slice cols x 1 row (X60..X81)
    (range(26, 36), [1], True),          # 18 x 1 (X36..X53)
    (range(26, 36), [0], True),          # 18 x 1, the other region
    (range(28, 36), [0, 1, 2], True),    # 14 x 3 (X40..X53)
    (range(36, 44), [0, 1, 2], True),    # 14 x 3 + a BRAM column
    (range(38, 44), [1, 2], True),       # 12 x 2 (X56..X67)
    (range(30, 36), [1, 2], True),       # 10 x 2 (X44..X53)
    (range(52, 56), [0, 1, 2], False),   # 8 x 3 (X82..X89)
    (range(26, 30), [0, 1, 2], False),   # 8 x 3 (X36..X43)
    (range(30, 36), [1], False),         # 10 x 1 (X44..X53, 500 slices)
    (range(30, 36), [0], False),         # 10 x 1, the other region
    (range(30, 36), [0, 1, 2], False),   # 10 x 3: refuted the first, height-blind model
]
# predicted to route before they were built, and routed (README "Validation")
VALIDATED = [
    (range(56, 66), [1]),                # 14 slice cols + BRAM + 2 DSP, 1 row: 700 slices
    (range(62, 72), [0]),                # 16 slice cols + BRAM + DSP, 1 row: 800 slices
    (range(38, 44), [0, 1, 2]),          # 12 x 3: the pins pack into a shorter band
    (range(58, 64), [0, 1, 2]),          # 10 x 3 + DSP
]
# predicted to route, and one module of 33 did not (20 signals): BRAM + DSP +
# 8 slice cols x 2 rows -- the model's documented miss (README)
MISSED = [(range(56, 62), [1, 2])]


def fits(fp, dev, cols, rows, pins=GA_PINS):
    r = fp.milp.pin_capacity(dev, list(cols), rows, pins)
    return min(r["area_margin"], r["width_margin"]) >= 1 - 1e-9


@pytest.mark.parametrize("cols,rows,routed", MEASURED)
def test_measured_regions_classified(fp, dev, cols, rows, routed):
    assert fits(fp, dev, cols, rows) == routed


@pytest.mark.parametrize("cols,rows", VALIDATED)
def test_validation_regions_route(fp, dev, cols, rows):
    assert fits(fp, dev, cols, rows)


@pytest.mark.parametrize("cols,rows", MISSED)
def test_the_documented_miss(fp, dev, cols, rows):
    # the model says this region routes; on the real part one module failed
    assert fits(fp, dev, cols, rows)


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
    # ... and its paired column takes no pins
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
    res = fp.milp.solve(dev, demands(pins=GA_PINS), objective=objective)
    for r in res["regions"].values():
        assert r["pins"] == GA_PINS
        assert r["pin_area_margin"] >= 1 - 1e-9
        assert r["pin_width_margin"] >= 1 - 1e-9
        assert fits(fp, dev, r["cols"], r["rows"])
        assert r["pin_cols"] >= 5


def test_densities_are_parameters(fp, dev):
    res = fp.milp.solve(dev, demands(pins=GA_PINS), objective="wr",
                        pin_cut_density=0.5 * fp.milp.PIN_CUT_DENSITY)
    half = 0.5 * fp.milp.PIN_CUT_DENSITY
    for r in res["regions"].values():
        assert r["pin_width_margin"] >= 1 - 1e-9
        assert fp.milp.pin_capacity(dev, r["cols"], r["rows"], GA_PINS,
                                    pin_cut_density=half)["width_margin"] \
            >= 1 - 1e-9
    # the default-density optimum does not survive the halved density
    base = fp.milp.solve(dev, demands(pins=GA_PINS), objective="wr")
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
