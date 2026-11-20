"""The device-model builder (tools/build_device_model.py) on a synthetic probe, and the
special-column probe's log parser (tools/probe_specials.py).

The synthetic part: two clock-region rows; CLB tile columns 2, 3 and 5 (slice pairs 0-1,
2-3, 4-5), a site-less special column 4 (interconnect only), interconnect pairs (2, 3) and
(4, 5).  Column 5's slices miss half of row 1 (an occluded cell), so row 1 is not fabric
there and its 25 sites are reported as excluded."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import build_device_model  # noqa: E402
import probe_specials      # noqa: E402


def synthetic_probe():
    ln = []
    for sx, tx, n1 in ((0, 2, 50), (1, 2, 50), (2, 3, 50), (3, 3, 50), (4, 5, 25), (5, 5, 25)):
        ln.append("COLROW SLICE %d 0 50" % sx)
        ln.append("COLROW SLICE %d 1 %d" % (sx, n1))
        ln.append("MAPLO SLICE_X%dY0 CLBLL_L_X%dY0" % (sx, tx))
    for x, side in ((2, "INT_L"), (3, "INT_R"), (4, "INT_L"), (5, "INT_R")):
        for y in range(100):
            ln.append("TILE 0 0 %s %s_X%dY%d" % (side, side, x, y))
    ln.append("TOTAL SLICE %d" % (4 * 100 + 2 * 75))
    ln.append("TOTAL RAMB36 0")
    ln.append("TOTAL DSP48 0")
    # one sampled interconnect tile: 16 horizontal singles, 4 vertical hexes
    for i in range(4):
        for w in ("EL1BEG", "ER1BEG", "WL1BEG", "WR1BEG"):
            ln.append("INTW INT_L_X2Y50 %s%d SINGLE 1 0" % (w, i))
        ln.append("INTW INT_L_X2Y50 NN6BEG%d VQUAD 0 6" % i)
    return "\n".join(ln) + "\n"


SPECIALS_LOG = """# puts "PROBE_SPECIAL 4 row 0 cols 2,3,4,5"
PROBE_SPECIAL 4 row 0 cols 2,3,4,5
CRITICAL WARNING: [Constraints 18-993] The Pblock pb has defined an area ...
The column of the split contains interconnect tile INT_L_X4Y49  (SLICE_X4Y49 SLICE_X5Y49).
CRITICAL WARNING: [Constraints 18-992]   Site Type: SLICEL excluded sites: 100
PROBE_SPECIAL_END 4
"""


def test_general_path(tmp_path):
    p = tmp_path / "probe.txt"
    p.write_text(synthetic_probe())
    m = build_device_model.build(str(p))
    assert m["nrows"] == 2
    assert m["columns"]["2"]["rows"] == [0, 1]
    assert m["columns"]["5"]["rows"] == [0]          # the occluded cell is not fabric
    assert m["specials"] == [4]
    assert m["excluded_sites"] == {"SLICE": 50}
    assert m["totals"]["slices"] == 500
    assert m["routing"]["pploc_wires_per_tile"] == 16
    assert m["routing"]["vertical_crossings_per_tile"] == 24


def test_specials_log(tmp_path):
    log = tmp_path / "probe_specials.log"
    log.write_text(SPECIALS_LOG)
    # the split names the special's own interconnect tile; the slice sites
    # identify the column that loses its placement
    assert probe_specials.parse_log(str(log)) == {4: [4, 5]}
    p = tmp_path / "probe.txt"
    p.write_text(synthetic_probe())
    m = build_device_model.build(str(p), str(log))
    assert m["special_splits"] == {"4": [5]}


def test_specials_log_must_cover_every_special(tmp_path):
    log = tmp_path / "probe_specials.log"
    log.write_text("")
    p = tmp_path / "probe.txt"
    p.write_text(synthetic_probe())
    with pytest.raises(AssertionError):
        build_device_model.build(str(p), str(log))


def test_bundled_special_splits(dev):
    # measured on xc7z020 (GA design and tools/probe_specials.py): covering
    # x=33 prohibits placement in CLB column 32; covering x=50 costs nothing
    assert dev.special_splits == {33: [32]}


def test_special_split_costs_capacity(fp, dev):
    """A region confined to columns 30..35 of row 1 (which hold the special
    x=33): its five CLB columns hold only 400 placeable slices, so 450
    slices cannot be met there.  (One DSP and one BRAM cell stay allowed,
    out of the region's reach in row 0, so every resource row of the model
    keeps a variable.)"""
    keep = set((c, 1) for c in range(30, 36)) | {(25, 0), (22, 0)}
    forbid = [(c, r) for c in dev.xs for r in range(dev.nrows)
              if (c, r) not in keep]
    res = fp.milp.solve(dev, {"rp0": {"lut": 0, "ff": 0, "bram": 0, "dsp": 0,
                                      "slices": 400}},
                        objective="wr", headroom=1.0, forbid_cells=forbid)
    r = res["regions"]["rp0"]
    assert 33 in r["cols"] and 32 in r["cols"]
    assert r["slices"] == 400                     # 32's 100 slices are not counted
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, {"rp0": {"lut": 0, "ff": 0, "bram": 0, "dsp": 0,
                                    "slices": 450}},
                      objective="wr", headroom=1.0, forbid_cells=forbid)
