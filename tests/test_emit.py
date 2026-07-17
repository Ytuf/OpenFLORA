"""Emitter round-trip against the hand floorplan that ran on silicon.

The case study's hand-written pblock ranges (the floorplan whose partials
were parsed byte-exactly) are the reference: serializing the same covered
tile columns/rows must reproduce those exact range lines.
"""

HAND_RP0_COLS = list(range(2, 22))     # tiles 2..21, clock-region row 0
HAND_RP1_COLS = list(range(38, 64))    # tiles 38..63, clock-region row 0

HAND_RP0_RANGES = [
    "SLICE_X0Y0:SLICE_X31Y49",
    "DSP48_X0Y0:DSP48_X1Y19",
    "RAMB18_X0Y0:RAMB18_X1Y19",
    "RAMB36_X0Y0:RAMB36_X1Y9",
]
HAND_RP1_RANGES = [
    "SLICE_X56Y0:SLICE_X101Y49",
    "DSP48_X3Y0:DSP48_X3Y19",
    "RAMB18_X4Y0:RAMB18_X4Y19",
    "RAMB36_X4Y0:RAMB36_X4Y9",
]


def test_hand_rp0_roundtrip(fp, dev):
    assert fp.emit.site_ranges(dev, HAND_RP0_COLS, [0]) == HAND_RP0_RANGES


def test_hand_rp1_roundtrip(fp, dev):
    assert fp.emit.site_ranges(dev, HAND_RP1_COLS, [0]) == HAND_RP1_RANGES


def test_multirow_ranges(fp, dev):
    # a full-height CLB+DSP span (tiles 24..27 exist on all three rows)
    got = fp.emit.site_ranges(dev, [24, 25, 26, 27], [0, 1, 2])
    assert got == ["SLICE_X34Y0:SLICE_X39Y149", "DSP48_X2Y0:DSP48_X2Y59"]


def test_pblocks_text(fp, dev):
    txt = fp.emit.pblocks_text([("rp0_inst", HAND_RP0_RANGES),
                                ("rp1_inst", HAND_RP1_RANGES)])
    blocks = txt.strip().split("\n\n")
    assert len(blocks) == 2
    b0 = blocks[0].splitlines()
    assert b0[0] == "# rp0_inst"
    assert b0[1:] == HAND_RP0_RANGES
    b1 = blocks[1].splitlines()
    assert b1[0] == "# rp1_inst"
    assert b1[1:] == HAND_RP1_RANGES


def test_pblocks_text_parses_back(fp, dev):
    # round-trip through a minimal reader of the format
    txt = fp.emit.pblocks_text([("rp0_inst", HAND_RP0_RANGES),
                                ("rp1_inst", HAND_RP1_RANGES)],
                               header="demo header\nsecond line")
    regions = []
    cur = None
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            cur = None
            continue
        if s.startswith("#"):
            continue
        if cur is None:
            cur = []
            regions.append(cur)
        cur.append(s)
    # header comment lines must not open a block; two range blocks survive
    assert regions == [HAND_RP0_RANGES, HAND_RP1_RANGES]


def test_xdc_text(fp, dev):
    txt = fp.emit.xdc_text([("rp0_inst", HAND_RP0_RANGES)],
                           cells={"rp0_inst": "top/rp0_inst"})
    assert "create_pblock pblock_rp0_inst" in txt
    assert ("add_cells_to_pblock [get_pblocks pblock_rp0_inst] "
            "[get_cells [list top/rp0_inst]]") in txt
    for rng in HAND_RP0_RANGES:
        assert ("resize_pblock [get_pblocks pblock_rp0_inst] -add {%s}"
                % rng) in txt
    assert ("set_property RESET_AFTER_RECONFIG true "
            "[get_pblocks pblock_rp0_inst]") in txt
    assert "set_property SNAPPING_MODE ON [get_pblocks pblock_rp0_inst]" in txt
    assert "set_property HD.RECONFIGURABLE true [get_cells top/rp0_inst]" in txt
