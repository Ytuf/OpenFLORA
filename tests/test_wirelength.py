"""The "wr+wl" wirelength objective (FLORA's a*WR + b*MIW, eq. 2).

These solves are on the bundled xc7z020 model with deliberately tiny
regions (one interconnect pair each) so the placement freedom is the
CENTROID, which is exactly what the wirelength term steers.  The device
CLB columns run tile-X 2..71; a covered pair forces both of its columns,
so a minimal region on row 0 near the left edge is {2,3} (centroid x 2.5)
and near the right edge is {70,71} (centroid x 70.5).

Every assertion is a PROVEN property of the optimum (the solver proves
optimality) -- either an exact achieved wirelength or a UNIQUE-optimum
centroid, never a solver-arbitrary tie.  Concretely the suite pins:

  * the exact achieved wirelength of hand-computable optima (catches a
    sign flip or a mis-linearized L1 term, which a mere <= monotonicity
    check cannot);
  * the VERTICAL axis -- an anchor at a nonzero clock-region row drives
    the row-END indicator / cy / anchor-y scaling (the real flow's
    weight-BRAM sits at a nonzero row);
  * per-connection WEIGHT semantics -- a 3-anchor weighted median whose
    optimum flips if the weight factor is dropped from the objective.
"""
import pytest


# tiny regions: one CLB cell (400 LUT / 100 slices) meets the demand at
# headroom 1.0, and the interconnect pair grows it to two columns.
SMALL = {"lut": 400, "ff": 100, "bram": 0, "dsp": 0, "slices": 100}
DEMANDS = {"rp0": dict(SMALL), "rp1": dict(SMALL)}
ONE = {"rp0": dict(SMALL)}

LEFT_ANCHOR = (2, 0)      # a device far-left CLB column, row 0
RIGHT_ANCHOR = (71, 0)    # a device far-right CLB column, row 0


def _solve(fp, dev, demands=DEMANDS, **kw):
    kw.setdefault("headroom", 1.0)
    return fp.milp.solve(dev, demands, **kw)


def test_default_path_byte_identical_ignores_connections(fp, dev):
    """A "frames"/"wr" solve ignores connections entirely: passing them
    must not change the proven optimum (the wl machinery is not built)."""
    def multiset(res):
        return sorted((r["frames"], r["bytes"])
                      for r in res["regions"].values())

    base = _solve(fp, dev, objective="frames")
    withconn = _solve(fp, dev, objective="frames",
                      connections=[("rp0", "rp1", 10)])
    assert multiset(base) == multiset(withconn)
    # and the wl reporting fields appear ONLY for the wr+wl objective
    assert "wirelength" not in base
    assert "centroid" not in base["regions"]["rp0"]


def test_result_structure(fp, dev):
    res = _solve(fp, dev, objective="wr+wl", a=1.0, b=1.0,
                 connections=[("rp0", RIGHT_ANCHOR, 100)])
    assert res["objective"] == "wr+wl"
    assert res["a"] == 1.0 and res["b"] == 1.0 and res["row_scale"] == 10
    wl = res["wirelength"]
    assert set(wl) == {"raw", "normalized", "wl_max"}
    assert wl["raw"] >= 0.0
    assert 0.0 <= wl["normalized"] <= 1.0
    assert abs(wl["normalized"] - wl["raw"] / wl["wl_max"]) < 1e-9
    for name in ("rp0", "rp1"):
        cx, cy = res["regions"][name]["centroid"]
        # centroid lands inside the device envelope, in (col, row) units
        assert dev.xs[0] <= cx <= dev.xs[-1]
        assert 0 <= cy <= dev.nrows - 1


def test_opposite_anchors_separate(fp, dev):
    """rp0 anchored far-left, rp1 anchored far-right: each hugs its own
    anchor, so rp0 ends up left of rp1.  This is the load-bearing
    behavior -- the wirelength term pulls a region toward the fixed block
    it talks to (the external weight-BRAM in the real flow).  The total
    achieved wirelength is the proven optimum: each region's minimal pair
    sits one half-column off its anchor, 100*0.5 + 100*0.5 = 100."""
    res = _solve(fp, dev, objective="wr+wl", a=0.01, b=1.0,
                 connections=[("rp0", LEFT_ANCHOR, 100),
                              ("rp1", RIGHT_ANCHOR, 100)])
    cx0 = res["regions"]["rp0"]["centroid"][0]
    cx1 = res["regions"]["rp1"]["centroid"][0]
    # each hugs its anchor within one pair-width
    assert abs(cx0 - LEFT_ANCHOR[0]) <= 1.5, cx0
    assert abs(cx1 - RIGHT_ANCHOR[0]) <= 1.5, cx1
    assert cx0 < cx1
    # exact achieved wirelength at the proven optimum
    assert abs(res["wirelength"]["raw"] - 100.0) < 1e-6, res["wirelength"]


def test_single_anchor_exact_pull(fp, dev):
    """One region connected to the far-right anchor hugs it: rp0 lands on
    {70,71} (cx 70.5), a proven half-column from column 71, so the
    achieved weighted wirelength is exactly 100 * 0.5 = 50.  Pins both the
    centroid and the reported wirelength; depends only on the connected
    region (no reliance on the unconnected region's arbitrary tie)."""
    res = _solve(fp, dev, objective="wr+wl", a=0.01, b=1.0,
                 connections=[("rp0", RIGHT_ANCHOR, 100)])
    cx0 = res["regions"]["rp0"]["centroid"][0]
    assert abs(cx0 - RIGHT_ANCHOR[0]) <= 1.5, cx0
    assert abs(res["wirelength"]["raw"] - 50.0) < 1e-6, res["wirelength"]


def test_sign_of_wl_term(fp, dev):
    """The wirelength term is MINIMIZED, not maximized: turning the weight
    up drives the achieved wirelength to the small optimum (50), not to
    the device-spanning maximum.  A sign flip (a*wr - b*wl) would push it
    toward wl_max instead -- this exact-value assertion catches that,
    where a bare `on <= off` monotonicity check does not."""
    res = _solve(fp, dev, objective="wr+wl", a=0.01, b=5.0,
                 connections=[("rp0", RIGHT_ANCHOR, 100)])
    wl = res["wirelength"]
    assert abs(wl["raw"] - 50.0) < 1e-6, wl
    assert wl["raw"] < 0.5 * wl["wl_max"], wl


def test_vertical_anchor_pull(fp, dev):
    """An anchor at a NONZERO clock-region row pulls the region up to that
    row -- exercising the row-END indicator, the cy centroid, and the
    anchor-y scaling (all silently zero when every anchor is at row 0).
    Anchor (60, 2): rp0 settles at row 2 (cy = 2.0 exactly) hugging
    column 60, achieved wirelength 100 * 0.5 = 50 (dx=0.5, dy=0)."""
    res = _solve(fp, dev, objective="wr+wl", a=0.01, b=1.0,
                 connections=[("rp0", (60, 2), 100)])
    cx0, cy0 = res["regions"]["rp0"]["centroid"]
    assert abs(cy0 - 2.0) < 1e-6, cy0          # pulled to the anchor's row
    assert abs(cx0 - 60) <= 1.5, cx0
    assert abs(res["wirelength"]["raw"] - 50.0) < 1e-6, res["wirelength"]


def test_weight_selects_heavier(fp, dev):
    """Per-connection weight has real effect: one region tied to three
    anchors at columns 2, 10, 71 with weights 100, 100, 250.  The weighted
    L1 optimum is the weighted median -- the 250-weight right anchor holds
    more than half the total weight (250 of 450), so the region hugs
    column 71 (cx 70.5).  If the weight factor were dropped from the
    objective the optimum would be the UNWEIGHTED median (column 10), so
    this assertion deterministically catches a weight-drop regression."""
    res = _solve(fp, dev, demands=ONE, objective="wr+wl", a=0.01, b=1.0,
                 connections=[("rp0", (2, 0), 100), ("rp0", (10, 0), 100),
                              ("rp0", (71, 0), 250)])
    cx0 = res["regions"]["rp0"]["centroid"][0]
    assert abs(cx0 - 71) <= 1.5, cx0           # hugs the heaviest anchor


def test_region_region_pull_adjacent(fp, dev):
    """Two regions connected to EACH OTHER (no anchor) pull adjacent:
    their centroids end within a pair-width of each other, on the same
    row (dy driven to 0)."""
    res = _solve(fp, dev, objective="wr+wl", a=0.01, b=1.0,
                 connections=[("rp0", "rp1", 100)])
    cx0 = res["regions"]["rp0"]["centroid"][0]
    cx1 = res["regions"]["rp1"]["centroid"][0]
    cy0 = res["regions"]["rp0"]["centroid"][1]
    cy1 = res["regions"]["rp1"]["centroid"][1]
    # adjacent on the same row: |dx| ~ one pair (2 columns), |dy| = 0
    assert abs(cx0 - cx1) <= 3.0, (cx0, cx1)
    assert abs(cy0 - cy1) < 1e-6, (cy0, cy1)
    # achieved wirelength is the minimal same-row separation, 100 * 2 = 200
    assert abs(res["wirelength"]["raw"] - 200.0) < 1e-6, res["wirelength"]


def test_pure_wirelength_a0(fp, dev):
    """a=0 is a legal pure-wirelength solve (area waste unpriced); the
    connected region still hugs its anchor."""
    res = _solve(fp, dev, objective="wr+wl", a=0.0, b=1.0,
                 connections=[("rp0", LEFT_ANCHOR, 100)])
    cx0 = res["regions"]["rp0"]["centroid"][0]
    assert abs(cx0 - LEFT_ANCHOR[0]) <= 1.5, cx0


# --- FLORA forbidden-region non-overlap (sec. 5.4) -------------------------

def test_forbid_default_byte_identical(fp, dev):
    """forbid_cells absent / empty leaves the model byte-for-byte
    unchanged (cell_ok reduces to device.cell_ok)."""
    def fm(res):
        return sorted((r["frames"], r["bytes"])
                      for r in res["regions"].values())
    base = _solve(fp, dev, objective="frames")
    empty = _solve(fp, dev, objective="frames", forbid_cells=[])
    assert fm(base) == fm(empty)


def test_forbid_cells_excludes_column(fp, dev):
    """A region may not cover a column forbidden at every row it could
    span -- the forbidden cell is treated like a device dead cell."""
    forbid = [(34, 0), (34, 1), (34, 2)]
    res = _solve(fp, dev, objective="frames", forbid_cells=forbid)
    for name in ("rp0", "rp1"):
        assert 34 not in res["regions"][name]["cols"], name


def test_forbid_and_pull_hugs_beside_bram(fp, dev):
    """The two FLORA roles for a static block together: pull rp0 toward a
    BRAM column AND forbid that column's cells.  rp0 must hug the CLB
    columns beside the BRAM without ever covering it -- the RP/BRAM
    overlap avoidance the wirelength floorplan needs."""
    forbid = [(36, 0), (36, 1), (36, 2)]
    res = _solve(fp, dev, objective="wr+wl", a=0.01, b=1.0,
                 forbid_cells=forbid, connections=[("rp0", (36, 1), 100)])
    r0 = res["regions"]["rp0"]
    assert 36 not in r0["cols"], r0["cols"]        # never covers the BRAM col
    assert abs(r0["centroid"][0] - 36) <= 3, r0["centroid"]  # hugs beside it


# --- fail-loud validation -------------------------------------------------

def test_wrwl_requires_connections(fp, dev):
    with pytest.raises(ValueError):
        _solve(fp, dev, objective="wr+wl")
    with pytest.raises(ValueError):
        _solve(fp, dev, objective="wr+wl", connections=[])


def test_bad_connection_triple(fp, dev):
    with pytest.raises(ValueError):
        _solve(fp, dev, objective="wr+wl", connections=[("rp0", "rp1")])


def test_unknown_region_endpoint(fp, dev):
    with pytest.raises(ValueError):
        _solve(fp, dev, objective="wr+wl",
               connections=[("rp0", "nope", 10)])


def test_bad_anchor_endpoint(fp, dev):
    with pytest.raises(ValueError):
        _solve(fp, dev, objective="wr+wl",
               connections=[("rp0", (1, 2, 3), 10)])


def test_nonpositive_weight(fp, dev):
    with pytest.raises(ValueError):
        _solve(fp, dev, objective="wr+wl",
               connections=[("rp0", RIGHT_ANCHOR, 0)])
