"""Partition-pin plans: emit.partpin_plan, partpin_cut_demand, and the CLI's
--pin-plan / --pins-file."""
import pytest

GA_PINS = 1596


def ga_pins():
    """GA b666's port bits, named as RFP names them: 690 slot bits each way
    (iK[b] / oK[b]) plus 216 memory and control bits that have no pair."""
    pins, pairs = [], []
    for k in range(690):
        pins += ["i%d[%d]" % (k // 32, k % 32), "o%d[%d]" % (k // 32, k % 32)]
        pairs.append(pins[-2:])
    pins += ["mem%d" % k for k in range(GA_PINS - len(pins))]
    return pins, pairs


def test_plan_pairs_share_a_tile(fp, dev):
    pins, pairs = ga_pins()
    cols, rows = list(range(52, 56)), [0, 1, 2]
    plan = dict(fp.emit.partpin_plan(dev, cols, rows, pins, pairs, per_tile=4))
    assert len(plan) == GA_PINS
    assert all(plan[a] == plan[b] for a, b in pairs)
    load = {}
    for t in plan.values():
        load[t] = load.get(t, 0) + 1
    assert max(load.values()) <= 4
    tiles = fp.emit.partpin_tiles(dev, cols, rows)
    assert set(plan.values()) <= set(tiles)
    # by default every interconnect tile of the region may take a pin
    assert len(tiles) == 4 * 150
    # trim=1 leaves the top and bottom edge rows free
    trimmed = fp.emit.partpin_tiles(dev, cols, rows, trim=1)
    assert not any(t.endswith("Y0") or t.endswith("Y149") for t in trimmed)
    assert len(trimmed) == 4 * 148


def test_plan_tiles_leave_out_split_columns(fp, dev):
    # tiles 30..35 cover the special x=33, which costs column 32
    tiles = fp.emit.partpin_tiles(dev, list(range(30, 36)), [1])
    xs = sorted(set(int(t.split("_X")[1].split("Y")[0]) for t in tiles))
    assert xs == [30, 31, 34, 35]
    assert tiles[0].startswith("INT_L_X30Y50")


def test_plan_too_many_pins(fp, dev):
    pins, pairs = ga_pins()
    with pytest.raises(ValueError):
        fp.emit.partpin_plan(dev, list(range(30, 36)), [1], pins, pairs,
                             per_tile=4)


def test_plan_xdc(fp, dev):
    plan = [("i0[0]", "INT_L_X52Y1"), ("o0[0]", "INT_L_X52Y1")]
    lines = fp.emit.partpin_xdc("top/rp0_inst", plan)
    assert lines[0] == ("set_property HD.PARTPIN_LOCS INT_L_X52Y1 "
                        "[get_pins {top/rp0_inst/i0[0]}]")


def test_csv_eighth_column_is_an_error(fp, tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("rp0,446,1738,0,0,1000,1596,648\n")
    with pytest.raises(ValueError):
        fp.cli.read_demands_csv(str(p))


def test_pins_file(fp, tmp_path):
    p = tmp_path / "pins.csv"
    p.write_text("# region,pin,pair\nrp0,i0[0],o0[0]\nrp0,o0[0]\nrp0,mem0\n")
    got = fp.cli.read_pins_csv(str(p))
    assert got == {"rp0": (["i0[0]", "o0[0]", "mem0"], [("i0[0]", "o0[0]")])}


def test_plan_cut_demand(fp, dev):
    """A fixed plan makes the cut demand exact, by direction: the pairs
    whose source and destination pins sit on opposite sides of a cut line.
    partpin_plan puts each pair in one tile, so it is 0; moving one pair's
    out-pin 138 rows north of its in-pin forces one northward crossing."""
    pins, pairs = ga_pins()
    plan = fp.emit.partpin_plan(dev, list(range(52, 56)), [0, 1, 2], pins, pairs,
                                per_tile=4)
    d = fp.emit.partpin_cut_demand(plan, pairs)
    assert (d["north"], d["south"], d["east"], d["west"]) == (0, 0, 0, 0)
    assert fp.emit.partpin_cut_check(dev, plan, pairs, list(range(52, 56)), [0, 1, 2]) == []
    loc = dict(plan)
    loc[pairs[0][0]] = "INT_L_X52Y2"
    loc[pairs[0][1]] = "INT_L_X52Y140"
    d = fp.emit.partpin_cut_demand(list(loc.items()), pairs)
    assert (d["north"], d["south"]) == (1, 0)


def test_plan_cut_check_is_one_way(fp, dev):
    """Every slot pair of a 4-column region split the same way: the north
    demand (690) exceeds the north-only wires plus every long line
    (4 x (83 + 30) = 452) although it is below the 196-per-column sum (784)."""
    ow = dev.raw["routing"]["one_way_crossings_per_tile"]
    assert ow["north"] + ow["south"] + ow["vertical_either"] == \
        dev.raw["routing"]["vertical_crossings_per_tile"]
    pins, pairs = ga_pins()
    plan = []
    for k, (a, b) in enumerate(pairs):
        x = 52 + k % 4
        plan += [(a, "INT_%s_X%dY10" % ("L" if x % 2 == 0 else "R", x)),
                 (b, "INT_%s_X%dY140" % ("L" if x % 2 == 0 else "R", x))]
    bad = fp.emit.partpin_cut_check(dev, plan, pairs, list(range(52, 56)), [0, 1, 2])
    assert bad and all(v[0] == "horizontal" and v[2] == len(pairs) for v in bad)
    assert len(pairs) < 4 * dev.raw["routing"]["vertical_crossings_per_tile"]


def test_plan_measurements(fp, dev):
    """The pin-plan builds (GA b666, xc7z020).  E3 / E3v: two 1-row,
    8-column regions routed every module with a plan of at most 5 a tile and
    without one; the site constraint accepts them as they are, and the plan
    has 384 pin tiles with the edge rows left free, 400 without."""
    for cols in (range(36, 44), range(56, 64)):
        r = fp.milp.pin_capacity(dev, list(cols), [1], GA_PINS)
        assert r["margin"] >= 1 - 1e-9
        # E3's plan left the edge rows free (trim=1): 384 pin tiles
        plan = fp.emit.partpin_plan(dev, list(cols), [1], *ga_pins(), per_tile=5, trim=1)
        assert len(set(t for _p, t in plan)) == 384
        # the defaults (at most 5 a tile, no trim) spread them over all 400
        plan = fp.emit.partpin_plan(dev, list(cols), [1], *ga_pins())
        assert len(set(t for _p, t in plan)) == 400


def test_cli_pin_plan_xdc(fp, tmp_path, capsys):
    """openflora plan --pin-plan N --pins-file F: the XDC places every pin of
    the regions bound to a cell, each pair in one tile."""
    pins, pairs = ga_pins()
    d = tmp_path / "d.csv"
    d.write_text("rp0,446,1738,0,0,1000,%d\nrp1,446,1738,0,0,1000,%d\n"
                 % (GA_PINS, GA_PINS))
    pf = tmp_path / "pins.csv"
    pair_of = dict(pairs)
    pf.write_text("".join("rp0,%s%s\n" % (p, "," + pair_of[p] if p in pair_of else "")
                          for p in pins))
    out = tmp_path / "fp.xdc"
    rc = fp.cli.main(["plan", "--csv", str(d), "--objective", "wr",
                      "--pin-plan", "5", "--pins-file", str(pf),
                      "--cell", "rp0=top/rp0_inst", "--cell", "rp1=top/rp1_inst",
                      "--out-xdc", str(out)])
    assert rc == 0
    capsys.readouterr()
    locs = {}
    for line in out.read_text().splitlines():
        if line.startswith("set_property HD.PARTPIN_LOCS"):
            tile = line.split()[2]
            pin = line.split("{top/rp0_inst/")[1][:-len("}]")]
            locs[pin] = tile
    assert len(locs) == GA_PINS
    assert all(locs[a] == locs[b] for a, b in pairs)
    # a pins-file region with no --cell is an error
    with pytest.raises(SystemExit):
        fp.cli.main(["plan", "--csv", str(d), "--objective", "wr",
                     "--pin-plan", "5", "--pins-file", str(pf),
                     "--cell", "rp1=top/rp1_inst", "--out-xdc", str(out)])


def test_plan_defaults(fp, dev):
    """At most 5 pins a tile (Vivado's own spreading target,
    PARTPIN_SPREADING) and no edge trim, unless the caller says otherwise."""
    import inspect
    sig = inspect.signature(fp.emit.partpin_plan).parameters
    assert sig["per_tile"].default == 5 and sig["trim"].default == 0
    assert inspect.signature(fp.emit.partpin_tiles).parameters["trim"].default == 0
    pins, pairs = ga_pins()
    plan = fp.emit.partpin_plan(dev, list(range(36, 44)), [1], pins, pairs)
    load = {}
    for _p, t in plan:
        load[t] = load.get(t, 0) + 1
    assert max(load.values()) <= 5
    # 1,596 pins do not fit 6 columns x 1 row at 5 a tile (1,500), and do at 6
    with pytest.raises(ValueError):
        fp.emit.partpin_plan(dev, list(range(38, 44)), [1], pins, pairs)
    fp.emit.partpin_plan(dev, list(range(38, 44)), [1], pins, pairs, per_tile=6)


def test_cli_pin_plan_without_n(fp, tmp_path, capsys):
    """--pin-plan alone means at most 5 a tile; --pin-plan-trim sets the
    edge rows left free."""
    pins, pairs = ga_pins()
    d = tmp_path / "d.csv"
    d.write_text("rp0,446,1738,0,0,1000,%d\nrp1,446,1738,0,0,1000,%d\n" % (GA_PINS, GA_PINS))
    pf = tmp_path / "pins.csv"
    pair_of = dict(pairs)
    pf.write_text("".join("rp0,%s%s\n" % (p, "," + pair_of[p] if p in pair_of else "")
                          for p in pins))
    for extra, rows_free in (([], False), (["--pin-plan-trim", "1"], True)):
        out = tmp_path / "fp.xdc"
        assert fp.cli.main(["plan", "--csv", str(d), "--objective", "wr",
                            "--pins-file", str(pf), "--cell", "rp0=top/rp0_inst",
                            "--cell", "rp1=top/rp1_inst", "--out-xdc", str(out),
                            "--pin-plan"] + extra) == 0
        capsys.readouterr()
        load = {}
        for line in out.read_text().splitlines():
            if line.startswith("set_property HD.PARTPIN_LOCS"):
                t = line.split()[2]
                load[t] = load.get(t, 0) + 1
        assert sum(load.values()) == GA_PINS and max(load.values()) <= 5
        ys = [int(t.split("Y")[-1]) for t in load]
        assert (min(ys) % 50 != 0 and max(ys) % 50 != 49) or not rows_free
