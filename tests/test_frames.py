"""Byte-exact reproduction of measured/recorded partial-bitstream sizes.

Fixtures (frame counts and byte sizes) are RECORDED measurements from real
Vivado 2019.1 DFX builds on a Pynq-Z2 (xc7z020); the .bit/.bin files
themselves are not shipped.  Sources:

  * the case-study design (examples/lenet_pynq) rp0/rp1: partial
    bitstreams PARSED with the package's UG470 parser -- 856,932 B /
    936,116 B, 2,120 / 2,316 FDRI frames, and the
    bytes = 404 * frames + 452 relation held exactly on both files.
  * an earlier two-region build on the same board, rp0/rp1: recorded file
    sizes 1,238,308 B / 1,091,252 B, which reconcile to exact integer
    frame counts (3,064 / 2,700) under the same relation; the files were
    no longer on disk to re-parse.

The hand floorplans behind these partials:
  * case study rp0 = tile columns 2..21,  clock-region row 0
  * case study rp1 = tile columns 38..63, clock-region row 0
  * earlier    rp0 = tile columns 2..31,  clock-region row 0
  * earlier    rp1 = tile columns 36..63, clock-region row 0
"""
import pytest

# (name, cols, rows, expected_frames, expected_bytes, provenance)
RECORDED = [
    ("casestudy_rp0", range(2, 22), [0], 2120, 856932, "parsed byte-exact"),
    ("casestudy_rp1", range(38, 64), [0], 2316, 936116, "parsed byte-exact"),
    ("earlier_rp0", range(2, 32), [0], 3064, 1238308, "recorded size reconciled"),
    ("earlier_rp1", range(36, 64), [0], 2700, 1091252, "recorded size reconciled"),
]


@pytest.mark.parametrize("name,cols,rows,exp_frames,exp_bytes,src",
                         RECORDED, ids=[r[0] for r in RECORDED])
def test_recorded_partial_sizes(fp, dev, name, cols, rows, exp_frames,
                                exp_bytes, src):
    frames, nbytes = fp.frames.region_frames(dev, cols, rows)
    assert frames == exp_frames
    assert nbytes == exp_bytes


@pytest.mark.parametrize("frames,nbytes",
                         [(r[3], r[4]) for r in RECORDED])
def test_bytes_frames_relation(dev, frames, nbytes):
    # bytes = frame_bytes * frames + overhead, exactly (measured relation)
    assert nbytes == dev.frame_bytes * frames + dev.overhead_bytes


def test_dead_cell_rejected(fp, dev):
    # tile column 2 exists only in clock-region row 0 on xc7z020 (the
    # processor subsystem occludes rows 1-2); a rectangle over it must fail.
    with pytest.raises(ValueError):
        fp.frames.region_frames(dev, [2], [0, 1])


def test_device_totals(dev):
    # probe-asserted totals of the bundled model
    assert dev.totals == {"slices": 13300, "lut": 53200, "ff": 106400,
                          "ramb36": 140, "dsp": 220}
    assert dev.total_ramb18() == 280
    assert dev.nrows == 3
    assert len(dev.columns) == 70
    assert dev.specials == [33, 50]
