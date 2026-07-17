"""Emit floorplans as site-range constraints.

Two output formats:
  * ``pblocks.txt`` -- one block of site-range lines per region, blocks
    separated by a blank line, '#' comments (a simple exchange format some
    DPR build flows consume directly);
  * XDC -- Vivado Tcl constraints (create_pblock / resize_pblock /
    add_cells_to_pblock / RESET_AFTER_RECONFIG), syntax per UG909.

Site-range serialization is exact for the bundled device models: covered
tile columns map back to SLICE / DSP48 / RAMB18+RAMB36 site ranges.  On
7-series a clock-region row spans 50 slice rows, 20 DSP48 rows, 20 RAMB18
rows and 10 RAMB36 rows; those per-row site counts come from the device
model's per_cell table.
"""

SLICE_ROWS_PER_REGION = 50


def site_ranges(device, cols, rows):
    """Serialize a covered rectangle to a list of site-range strings.

    Round-trips the measured hand floorplans exactly (see tests/test_emit.py).
    """
    rows = sorted(rows)
    r0, r1 = rows[0], rows[-1]
    ranges = []
    clb = sorted(c for c in cols if device.col_type(c) == "CLB")
    if clb:
        lo = device.columns[clb[0]]["slice_lo"]
        hi = device.columns[clb[-1]]["slice_hi"]
        ranges.append("SLICE_X%dY%d:SLICE_X%dY%d"
                      % (lo, SLICE_ROWS_PER_REGION * r0,
                         hi, SLICE_ROWS_PER_REGION * r1 + SLICE_ROWS_PER_REGION - 1))
    dsp_n = device.per_cell["dsp"]
    dsp = sorted(device.columns[c]["dsp_site"] for c in cols
                 if device.col_type(c) == "DSP")
    if dsp:
        ranges.append("DSP48_X%dY%d:DSP48_X%dY%d"
                      % (dsp[0], dsp_n * r0, dsp[-1], dsp_n * r1 + dsp_n - 1))
    b18_n = device.per_cell["ramb18"]
    b36_n = device.per_cell["ramb36"]
    bram = sorted(device.columns[c]["bram_site"] for c in cols
                  if device.col_type(c) == "BRAM")
    if bram:
        ranges.append("RAMB18_X%dY%d:RAMB18_X%dY%d"
                      % (bram[0], b18_n * r0, bram[-1], b18_n * r1 + b18_n - 1))
        ranges.append("RAMB36_X%dY%d:RAMB36_X%dY%d"
                      % (bram[0], b36_n * r0, bram[-1], b36_n * r1 + b36_n - 1))
    return ranges


def pblocks_text(regions, header=None):
    """regions: list of (name, list-of-range-strings). Returns pblocks.txt text."""
    out = []
    if header:
        for ln in header.splitlines():
            out.append(("# " + ln).rstrip())
        out.append("")
    for k, (name, ranges) in enumerate(regions):
        if k:
            out.append("")
        out.append("# " + name)
        out.extend(ranges)
    return "\n".join(out) + "\n"


def xdc_text(regions, cells=None, reset_after_reconfig=True,
             snapping_mode=True, header=None):
    """regions: list of (name, list-of-range-strings).

    cells: optional dict region-name -> hierarchical cell path; when given,
    emits add_cells_to_pblock and HD.RECONFIGURABLE for that cell.
    Command syntax per UG909 (Vivado Design Suite User Guide: Partial
    Reconfiguration / Dynamic Function eXchange).
    """
    out = []
    if header:
        for ln in header.splitlines():
            out.append(("# " + ln).rstrip())
        out.append("")
    for name, ranges in regions:
        pb = "pblock_" + name
        out.append("create_pblock %s" % pb)
        if cells and name in cells:
            out.append("add_cells_to_pblock [get_pblocks %s] [get_cells [list %s]]"
                       % (pb, cells[name]))
        for rng in ranges:
            out.append("resize_pblock [get_pblocks %s] -add {%s}" % (pb, rng))
        if reset_after_reconfig:
            out.append("set_property RESET_AFTER_RECONFIG true [get_pblocks %s]" % pb)
        if snapping_mode:
            out.append("set_property SNAPPING_MODE ON [get_pblocks %s]" % pb)
        if cells and name in cells:
            out.append("set_property HD.RECONFIGURABLE true [get_cells %s]"
                       % cells[name])
        out.append("")
    return "\n".join(out)
