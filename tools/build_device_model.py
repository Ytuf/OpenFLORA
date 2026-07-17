"""Build a device-model JSON from a Vivado geometry probe.

Usage:
    python tools/build_device_model.py probe_geometry_out.txt out.json

The probe file is produced by tools/probe_geometry.tcl run against the real
part in Vivado (see that file for the recipe).  This script reduces it to
the JSON consumed by the package's device module.

IMPORTANT -- the frame constants below (FRAMES, BRAM_CONTENT_FRAMES,
PREAMBLE_FRAMES, OVERHEAD_BYTES) are 7-series values MEASURED from real
xc7z020 partial bitstreams (parsed with the package's bitparse module) and
corroborated by UG470 (101 words/frame) and Project X-Ray's public 7-series
documentation (CLB = 36 frames).  For a different device family, re-measure
them: generate two partial bitstreams with known pblock rectangles, parse
them, and solve for the per-column-type frame counts before trusting the
frames objective.  The geometry part (columns, rows, pairs, forbidden
cells) is fully probe-derived and needs no such calibration.

The script asserts its reduction against the probe's own TOTAL lines, and
sanity-checks slice pairing and column heights, so a silently-misread probe
fails loudly.
"""
import json
import sys

NROWS = 3                  # clock-region rows (xc7z020: Y0/Y1/Y2)
FRAMES = {"CLB": 36, "BRAM": 28, "DSP": 28, "OTHER30": 30}
BRAM_CONTENT_FRAMES = 128
FRAME_BYTES = 404          # 101 words x 4 (UG470 frame length)
PREAMBLE_FRAMES = 228      # measured: identical fixed preamble in partials
OVERHEAD_BYTES = 452       # measured: pre-sync header + command words

SLICES_PER_CELL = 100      # a CLB tile column = 2 slice columns x 50 sites/region
LUT_PER_CELL = 400
FF_PER_CELL = 800
RAMB36_PER_CELL = 10
RAMB18_PER_CELL = 20
DSP_PER_CELL = 20


def name_xy(name):
    i = name.rfind("_X")
    base = name[i + 2:]
    j = base.find("Y")
    return int(base[:j]), int(base[j + 1:])


def build(probe_path):
    slice_rows = {}       # slice site X -> rows where the column exists
    ramb36_rows = {}      # ramb36 site X -> rows
    dsp_rows = {}         # dsp48 site X -> rows
    slice_to_tile = {}    # slice site X -> tile col X (row 0)
    ramb_to_tile = {}     # ramb36 site X -> tile col X
    dsp_to_tile = {}      # dsp48 site X -> tile col X
    int_rows = {}         # (side, tile col X) -> rows where INT exists

    for ln in open(probe_path):
        ln = ln.strip()
        if ln.startswith("COL SLICE_X"):
            parts = ln.split()
            x = int(parts[1][len("SLICE_X"):])
            n = int(parts[2][2:])
            slice_rows[x] = [0] if n == 50 else [0, 1, 2]
            if n not in (50, 150):
                raise AssertionError("unexpected slice column height " + ln)
        elif ln.startswith("COL RAMB36_X"):
            parts = ln.split()
            x = int(parts[1][len("RAMB36_X"):])
            n = int(parts[2][2:])
            ramb36_rows[x] = [0] if n == 10 else [0, 1, 2]
            if n not in (10, 30):
                raise AssertionError("unexpected bram column height " + ln)
        elif ln.startswith("COL DSP48_X"):
            parts = ln.split()
            x = int(parts[1][len("DSP48_X"):])
            n = int(parts[2][2:])
            dsp_rows[x] = [0] if n == 20 else [0, 1, 2]
            if n not in (20, 60):
                raise AssertionError("unexpected dsp column height " + ln)
        elif ln.startswith("MAP SLICE_"):
            _, site, tile = ln.split()
            sx, sy = name_xy(site)
            tx, ty = name_xy(tile)
            slice_to_tile[sx] = tx
        elif ln.startswith("MAPB RAMB36_"):
            _, site, tile = ln.split()
            sx, sy = name_xy(site)
            tx, ty = name_xy(tile)
            ramb_to_tile[sx] = tx
        elif ln.startswith("MAPD DSP48_"):
            _, site, tile = ln.split()
            sx, sy = name_xy(site)
            tx, ty = name_xy(tile)
            dsp_to_tile[sx] = tx
        elif ln.startswith("TILE "):
            _, col, row, ty, name = ln.split()
            if ty in ("INT_L", "INT_R"):
                x, y = name_xy(name)
                int_rows.setdefault((ty, x), set()).add(y // 50)

    # ---- fabric columns keyed by tile-name X -------------------------------
    cols = {}
    for sx, tx in slice_to_tile.items():
        c = cols.setdefault(tx, {"type": "CLB", "rows": slice_rows[sx],
                                 "slice_lo": sx, "slice_hi": sx})
        c["slice_lo"] = min(c["slice_lo"], sx)
        c["slice_hi"] = max(c["slice_hi"], sx)
        if set(c["rows"]) != set(slice_rows[sx]):
            raise AssertionError("slice pair row mismatch tile %d" % tx)
    for bx, tx in ramb_to_tile.items():
        cols[tx] = {"type": "BRAM", "rows": ramb36_rows[bx], "bram_site": bx}
    for dx, tx in dsp_to_tile.items():
        cols[tx] = {"type": "DSP", "rows": dsp_rows[dx], "dsp_site": dx}

    # sanity: each CLB tile col carries exactly one slice pair (2k, 2k+1)
    for tx, c in cols.items():
        if c["type"] == "CLB":
            if c["slice_hi"] - c["slice_lo"] != 1 or c["slice_lo"] % 2 != 0:
                raise AssertionError("bad slice pair at tile %d: %s" % (tx, c))

    # ---- special columns (no user sites): classify from INT presence -------
    all_x = sorted(cols.keys())
    lo_x, hi_x = all_x[0], all_x[-1]
    known = set(cols.keys())
    specials = []
    for x in range(lo_x, hi_x + 1):
        if x in known:
            continue
        rows = sorted(int_rows.get(("INT_L", x), set()) |
                      int_rows.get(("INT_R", x), set()))
        specials.append(x)
        cols[x] = {"type": "OTHER30", "rows": rows}

    # ---- INT pair map: (even x, odd x+1) back-to-back, per row -------------
    pairs = {}
    for x in range(lo_x - (lo_x % 2), hi_x + 1, 2):
        rl = int_rows.get(("INT_L", x), set())
        rr = int_rows.get(("INT_R", x + 1), set())
        both = sorted(rl & rr)
        if both:
            pairs[x] = both

    model = {
        "nrows": NROWS,
        "frames": FRAMES,
        "bram_content_frames": BRAM_CONTENT_FRAMES,
        "frame_bytes": FRAME_BYTES,
        "preamble_frames": PREAMBLE_FRAMES,
        "overhead_bytes": OVERHEAD_BYTES,
        "per_cell": {"slices": SLICES_PER_CELL, "lut": LUT_PER_CELL,
                     "ff": FF_PER_CELL, "ramb36": RAMB36_PER_CELL,
                     "ramb18": RAMB18_PER_CELL, "dsp": DSP_PER_CELL},
        "columns": {str(x): cols[x] for x in sorted(cols)},
        "pairs": {str(x): pairs[x] for x in sorted(pairs)},
        "specials": specials,
    }

    # ---- device totals: assert against the probe's own TOTAL lines ---------
    tot_sl = sum(SLICES_PER_CELL * len(c["rows"]) for c in cols.values()
                 if c["type"] == "CLB")
    tot_br = sum(RAMB36_PER_CELL * len(c["rows"]) for c in cols.values()
                 if c["type"] == "BRAM")
    tot_dsp = sum(DSP_PER_CELL * len(c["rows"]) for c in cols.values()
                  if c["type"] == "DSP")
    for ln in open(probe_path):
        if ln.startswith("TOTAL SLICE"):
            assert tot_sl == int(ln.split()[2]), (tot_sl, ln)
        if ln.startswith("TOTAL RAMB36"):
            assert tot_br == int(ln.split()[2]), (tot_br, ln)
        if ln.startswith("TOTAL DSP48"):
            assert tot_dsp == int(ln.split()[2]), (tot_dsp, ln)
    model["totals"] = {"slices": tot_sl, "lut": tot_sl * 4, "ff": tot_sl * 8,
                       "ramb36": tot_br, "dsp": tot_dsp}
    return model


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    probe_path, out_path = sys.argv[1], sys.argv[2]
    m = build(probe_path)
    with open(out_path, "w") as f:
        json.dump(m, f, indent=1)
    print("device model written to %s: %d columns, %d pairs, specials=%s"
          % (out_path, len(m["columns"]), len(m["pairs"]), m["specials"]))
    print("totals:", m["totals"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
