"""End-to-end solves on the bundled xc7z020 model.

Expected values are the RECORDED optima of the current model on the case
study (examples/lenet_pynq).  History of measured placement failures that
shaped the model (all 2026-07-16):

  * Round 1: the pre-alignment derate-1.0 optimum (922 frames / 372,940 B,
    spine column at the region edge) FAILED placement (Vivado [Constraints
    18-993]: edge split of a back-to-back interconnect pair, 100 SLICEL
    prohibited, rp1 at 107.3 % post-exclusion demand).  Fixes: the
    edge-alignment constraint + the calibrated ``headroom`` knob.
  * Round 2: the re-solve (1,050 frames / 424,652 B per region) rebuilt
    with zero pair-split warnings but FAILED detail placement on slice
    packing ([Place 30-487]: ~930 slices needed on a 900-slice pblock at
    only 72 % LUT / 28 % FF utilization; 33 control sets -- one unique
    control set per slice pins FF packing).  Fix: the ``slices`` demand
    column, measured occupied-slice maxima from the proven builds'
    routed checkpoints (rp0 1,127 / rp1 1,264).

Optima recorded with the measured slice demands (rp0/rp1 now asymmetric;
the two regions' spots can swap among frame-ties, so per-region values
are asserted as a multiset):

  * frames, defaults (derate 1.0, headroom 0.93) -> {1,482 fr / 599,180 B;
    1,352 fr / 546,660 B}, total 2,834 frames;
  * frames, derate 1.0, headroom 1.0 -> {1,320 fr / 533,732 B;
    1,352 fr / 546,660 B}, total 2,672 frames;
  * frames, derate 0.5, headroom 1.0 -> {2,444 fr / 987,828 B;
    2,742 fr / 1,108,220 B}, total 5,186 frames;
  * wr, derate 1.0, headroom 1.0 -> {12 CLB + 1 DSP + 1 BRAM cells;
    13 CLB + 1 DSP + 1 BRAM cells}, single-row spans.

Because the solver PROVES optimality, every optimal solution must hit
these totals; only WHERE the rectangles land is solver-arbitrary, so
geometry is checked for validity rather than pinned.
"""
import os

import pytest

DEMANDS = {
    "rp0": {"lut": 2874, "ff": 2026, "bram": 0, "dsp": 12, "slices": 1127},
    "rp1": {"lut": 2972, "ff": 2026, "bram": 0, "dsp": 12, "slices": 1264},
}
STATIC_BRAM_RAMB18 = 201   # case-study static design: 100 RAMB36 + 1 RAMB18


def check_valid(fp, dev, result, demands, derate, headroom=1.0):
    """Structural validity of a solved floorplan."""
    all_cells = set()
    for name, r in result["regions"].items():
        cols, rows = r["cols"], r["rows"]
        assert cols and rows
        # contiguous column span and row span
        i0 = dev.xs.index(cols[0])
        assert cols == dev.xs[i0:i0 + len(cols)]
        assert rows == list(range(rows[0], rows[0] + len(rows)))
        # no dead cells; frame accounting agrees with the frames module
        frames, nbytes = fp.frames.region_frames(dev, cols, rows)
        assert (frames, nbytes) == (r["frames"], r["bytes"])
        # interconnect-pair legality on every covered row
        cs = set(cols)
        for x, prows in dev.pairs.items():
            for row in rows:
                if row in prows:
                    assert ((x in cs) == ((x + 1) in cs)), \
                        "pair (%d,%d) split on row %d" % (x, x + 1, row)
        # edge alignment ([Constraints 18-993]): both x-edges must land on
        # pair boundaries -- edge columns carry sites (a site-less special
        # column at the edge cannot be expressed in the emitted site
        # ranges, so the physical pblock edge would retract mid-pair),
        # the left edge opens a pair, the right edge closes one.
        assert dev.col_type(cols[0]) != "OTHER30", \
            "region %s starts on a site-less column" % name
        assert dev.col_type(cols[-1]) != "OTHER30", \
            "region %s ends on a site-less column" % name
        assert cols[0] % 2 == 0, \
            "region %s left edge %d is mid-pair" % (name, cols[0])
        assert cols[-1] % 2 == 1, \
            "region %s right edge %d is mid-pair" % (name, cols[-1])
        # demands met under derate * headroom
        d = demands[name]
        assert derate * headroom * r["lut"] >= d["lut"]
        assert derate * headroom * r["ff"] >= d["ff"]
        assert derate * headroom * r["dsp"] >= d["dsp"]
        assert derate * headroom * r["bram_ramb18"] >= d["bram"]
        # slice occupancy ([Place 30-487]): covered slices must clear the
        # slice demand (explicit, or the ceil(lut/4) default)
        assert derate * headroom * r["slices"] >= fp.milp.slice_demand(d)
        assert r["slices_demand"] == fp.milp.slice_demand(d)
        # no overlap
        cells = {(c, row) for c in cols for row in rows}
        assert not (cells & all_cells)
        all_cells |= cells
    # static BRAM reservation honored
    covered_b18 = sum(r["bram_ramb18"] for r in result["regions"].values())
    assert covered_b18 <= dev.total_ramb18() - STATIC_BRAM_RAMB18


def frame_multiset(res):
    return sorted((r["frames"], r["bytes"]) for r in res["regions"].values())


def test_frames_objective_defaults(fp, dev):
    """The case study at the shipped defaults (headroom 0.93).

    Regression for BOTH measured 2026-07-16 placement failures: the solved
    rectangles must have both x-edges on interconnect-pair boundaries
    (round 1; check_valid asserts it), and the covered SLICE capacity
    times the headroom must clear the measured occupied-slice maxima
    (round 2, [Place 30-487]: the slice-blind optimum packed a module
    that occupies 1,264 slices as routed into a 900-slice pblock).
    """
    res = fp.milp.solve(dev, DEMANDS, objective="frames",
                        static_bram_reserve=STATIC_BRAM_RAMB18)
    assert res["headroom"] == 0.93
    check_valid(fp, dev, res, DEMANDS, 1.0, headroom=0.93)
    assert frame_multiset(res) == [(1352, 546660), (1482, 599180)]
    for r in res["regions"].values():
        assert not r["slices_demand_derived"]


def test_frames_objective_derate1_headroom1(fp, dev):
    res = fp.milp.solve(dev, DEMANDS, objective="frames", derate=1.0,
                        headroom=1.0,
                        static_bram_reserve=STATIC_BRAM_RAMB18)
    check_valid(fp, dev, res, DEMANDS, 1.0)
    assert frame_multiset(res) == [(1320, 533732), (1352, 546660)]


def test_wr_objective_derate1_headroom1(fp, dev):
    res = fp.milp.solve(dev, DEMANDS, objective="wr", derate=1.0,
                        headroom=1.0,
                        static_bram_reserve=STATIC_BRAM_RAMB18)
    check_valid(fp, dev, res, DEMANDS, 1.0)
    # optimal wasted-resources cover with the measured slice demands:
    # 12 CLB cells for rp0 (1,127 slices), 13 for rp1 (1,264), each plus
    # 1 DSP cell and 1 BRAM cell (the single-row spans the optimum picks
    # cannot reach their DSP column without crossing a BRAM column; the
    # solver proves no BRAM-free cover does better)
    total_wr = sum(r["wr_covered"] for r in res["regions"].values())
    assert abs(total_wr - ((12 + 13) * 100 / 13300
                           + 2 * (20 / 220) + 2 * (10 / 140))) < 1e-9


def test_frames_objective_derate05_headroom1(fp, dev):
    res = fp.milp.solve(dev, DEMANDS, objective="frames", derate=0.5,
                        headroom=1.0,
                        static_bram_reserve=STATIC_BRAM_RAMB18)
    check_valid(fp, dev, res, DEMANDS, 0.5)
    assert frame_multiset(res) == [(2444, 987828), (2742, 1108220)]


def test_slice_demand_binds_where_lut_fits(fp, dev):
    """A slice-bound instance: LUT capacity alone would fit in ONE CLB
    cell (400 LUTs >= 400 demanded), but the measured 930-slice demand
    (the [Place 30-487] round-2 number) forces >= 10 CLB cells at
    headroom 1.0.  This is the miscompile class round 2 hit: without the
    slices column the solver returns a region a real module cannot
    place into.
    """
    lut_only = {"rp0": {"lut": 400, "ff": 100, "bram": 0, "dsp": 0}}
    res = fp.milp.solve(dev, lut_only, objective="frames", headroom=1.0)
    check_valid(fp, dev, res, lut_only, 1.0)
    r = res["regions"]["rp0"]
    assert r["slices_demand_derived"]
    assert r["slices_demand"] == 100          # ceil(400/4) default
    assert r["slices"] <= 200                 # 1-2 CLB cells suffice

    sliced = {"rp0": {"lut": 400, "ff": 100, "bram": 0, "dsp": 0,
                      "slices": 930}}
    res = fp.milp.solve(dev, sliced, objective="frames", headroom=1.0)
    check_valid(fp, dev, res, sliced, 1.0)
    r = res["regions"]["rp0"]
    assert not r["slices_demand_derived"]
    assert r["slices_demand"] == 930
    assert r["slices"] >= 930                 # >= 10 CLB cells covered


def test_slice_demand_default_is_ceil_lut_over_4(fp):
    assert fp.milp.slice_demand({"lut": 400}) == 100
    assert fp.milp.slice_demand({"lut": 401}) == 101
    assert fp.milp.slice_demand({"lut": 0}) == 0
    assert fp.milp.slice_demand({}) == 0
    assert fp.milp.slice_demand({"lut": 400, "slices": 930}) == 930
    assert fp.milp.slice_demand({"lut": 400, "slices": None}) == 100


def test_infeasible_raises(fp, dev):
    too_big = {"rp0": {"lut": 60000, "ff": 0, "bram": 0, "dsp": 0}}
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, too_big, objective="frames")
    # slice demand alone can also be infeasible
    too_many_slices = {"rp0": {"lut": 0, "ff": 0, "bram": 0, "dsp": 0,
                               "slices": 20000}}
    with pytest.raises(RuntimeError):
        fp.milp.solve(dev, too_many_slices, objective="frames")


def test_example_csv_matches(fp):
    """The shipped example demands CSV parses to the fixture demands."""
    here = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(here, os.pardir, "examples", "lenet_pynq",
                            "demands.csv")
    from_csv = fp.cli.read_demands_csv(csv_path)
    assert from_csv == DEMANDS


def test_csv_reader(fp, tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("# comment\nname,lut,ff,bram,dsp\na,1,2,3,4\nb,5,6,7,8\n")
    got = fp.cli.read_demands_csv(str(p))
    assert got == {"a": {"lut": 1, "ff": 2, "bram": 3, "dsp": 4},
                   "b": {"lut": 5, "ff": 6, "bram": 7, "dsp": 8}}
    # headerless is accepted too
    p.write_text("a,1,2,3,4\n")
    assert fp.cli.read_demands_csv(str(p)) == {
        "a": {"lut": 1, "ff": 2, "bram": 3, "dsp": 4}}
    # the optional sixth field is the slice demand
    p.write_text("name,lut,ff,bram,dsp,slices\na,1,2,3,4,9\n")
    assert fp.cli.read_demands_csv(str(p)) == {
        "a": {"lut": 1, "ff": 2, "bram": 3, "dsp": 4, "slices": 9}}
    # mixed arity: rows without it just take the derived default later
    p.write_text("a,1,2,3,4,9\nb,5,6,7,8\n")
    assert fp.cli.read_demands_csv(str(p)) == {
        "a": {"lut": 1, "ff": 2, "bram": 3, "dsp": 4, "slices": 9},
        "b": {"lut": 5, "ff": 6, "bram": 7, "dsp": 8}}
    # wrong arity fails loudly
    p.write_text("a,1,2,3\n")
    with pytest.raises(ValueError):
        fp.cli.read_demands_csv(str(p))
    p.write_text("a,1,2,3,4,9,9\n")
    with pytest.raises(ValueError):
        fp.cli.read_demands_csv(str(p))
    # negative slices fail loudly
    p.write_text("a,1,2,3,4,-9\n")
    with pytest.raises(ValueError):
        fp.cli.read_demands_csv(str(p))
    # duplicate names fail loudly
    p.write_text("a,1,2,3,4\na,1,2,3,4\n")
    with pytest.raises(ValueError):
        fp.cli.read_demands_csv(str(p))
