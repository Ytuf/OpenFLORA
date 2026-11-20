"""Partition-pin plans (emit.partpin_plan, the CLI's --pin-plan / --pins-file) and the
pass-through demand."""
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
    # the edge rows stay free, the special column's interconnect is never used
    assert not any(t.endswith("Y0") or t.endswith("Y149") for t in tiles)
    assert len(tiles) == 4 * 148


def test_plan_tiles_leave_out_split_columns(fp, dev):
    # tiles 30..35 cover the special x=33, which costs column 32
    tiles = fp.emit.partpin_tiles(dev, list(range(30, 36)), [1])
    xs = sorted(set(int(t.split("_X")[1].split("Y")[0]) for t in tiles))
    assert xs == [30, 31, 34, 35]
    assert tiles[0].startswith("INT_L_X30Y51")


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


def test_passthrough_default_is_half_the_pins(fp):
    assert fp.milp.passthrough_demand({"pins": 1596}) == 798
    assert fp.milp.passthrough_demand({"pins": 1595}) == 798
    assert fp.milp.passthrough_demand({"pins": 1596, "passthrough": 648}) == 648
    assert fp.milp.passthrough_demand({"pins": 1596, "passthrough": 0}) == 0


def test_passthrough_eases_width(fp, dev):
    cols, rows = list(range(22, 26)), [0, 1, 2]       # 4 columns, full height
    worst = fp.milp.pin_capacity(dev, cols, rows, 1325)
    low = fp.milp.pin_capacity(dev, cols, rows, 1325, passthrough=133)
    assert low["width_margin"] > worst["width_margin"]
    assert low["area_margin"] == worst["area_margin"]


def test_csv_passthrough_column(fp, tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("name,lut,ff,bram,dsp,slices,pins,passthrough\n"
                 "rp0,446,1738,0,0,1000,1596,648\n")
    d = fp.cli.read_demands_csv(str(p))
    assert d["rp0"]["pins"] == 1596 and d["rp0"]["passthrough"] == 648
    p.write_text("rp0,446,1738,0,0,1000,1596,1600\n")
    with pytest.raises(ValueError):          # more pass-through than pins
        fp.cli.read_demands_csv(str(p))
    p.write_text("rp0,446,1738,0,0,1000,1596,648,1\n")
    with pytest.raises(ValueError):
        fp.cli.read_demands_csv(str(p))


def test_pins_file(fp, tmp_path):
    p = tmp_path / "pins.csv"
    p.write_text("# region,pin,pair\nrp0,i0[0],o0[0]\nrp0,o0[0]\nrp0,mem0\n")
    got = fp.cli.read_pins_csv(str(p))
    assert got == {"rp0": (["i0[0]", "o0[0]", "mem0"], [("i0[0]", "o0[0]")])}


def test_plan_measurements(fp, dev):
    """The pin-plan builds (GA b666, xc7z020).  E3 / E3v: two 1-row,
    8-column regions routed every module with a plan of at most 5 a tile and
    without one, and the model accepts them as they are.  E2: two 4-column,
    3-row regions; a plan routed 12 of 16 modules but not all, and the model
    rejects them (the solver gives a plan no credit)."""
    m = fp.milp
    for cols in (range(36, 44), range(56, 64)):
        r = m.pin_capacity(dev, list(cols), [1], GA_PINS, 648)
        assert min(r["area_margin"], r["width_margin"],
                   r["height_margin"]) >= 1 - 1e-9
        plan = fp.emit.partpin_plan(dev, list(cols), [1], *ga_pins(), per_tile=5)
        assert len(set(t for _p, t in plan)) == 384
    for cols in (range(52, 56), range(38, 42)):
        r = m.pin_capacity(dev, list(cols), [0, 1, 2], GA_PINS, 648)
        assert r["width_margin"] < 1


def test_cli_pin_plan_xdc(fp, tmp_path, capsys):
    """openflora plan --pin-plan N --pins-file F: the XDC places every pin of
    the regions bound to a cell, each pair in one tile."""
    pins, pairs = ga_pins()
    d = tmp_path / "d.csv"
    d.write_text("rp0,446,1738,0,0,1000,%d,648\nrp1,446,1738,0,0,1000,%d,648\n"
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
