"""Device model: geometry + frame constants for one FPGA part.

A device model is a JSON file (see ``devices/xc7z020.json``) produced by
``tools/build_device_model.py`` from a Vivado probe of the real part
(``tools/probe_geometry.tcl``).  Axes follow the FLORA paper's convention:

  x-axis: fabric tile columns indexed by their tile-name X coordinate
          (measured fact on xc7z020: the FAR major-column address in the
          partial bitstream equals the tile-name X, proven by parsing the
          partial bitstreams -- see ``bitparse.py``).
  y-axis: clock-region rows 0..nrows-1 (row r holds site rows 50r..50r+49
          on 7-series).

Column types and per-clock-region contents:
  CLB     : one CLB tile column = 2 slice columns = per_cell["slices"] slices
  BRAM    : per_cell["ramb36"] RAMB36 = per_cell["ramb18"] RAMB18
  DSP     : per_cell["dsp"] DSP48
  OTHER30 : special column with no user resources (clock spine / config
            column class); costs frames["OTHER30"] configuration frames.

Frame accounting constants (all measured from real partial bitstreams on
xc7z020, corroborated by UG470 and Project X-Ray -- see README provenance):
  frames          : configuration frames per column per clock-region row
  bram_content_frames : extra BRAM-content frames per BRAM column per row
  frame_bytes     : bytes per frame (101 words x 4 on 7-series, UG470)
  preamble_frames : fixed frame overhead per partial bitstream
  overhead_bytes  : fixed byte overhead (header + command words)
"""
import json
import os

try:
    from importlib.resources import files as _res_files
except ImportError:  # pragma: no cover
    _res_files = None


class Device:
    """Loaded device model with convenient typed accessors."""

    def __init__(self, raw):
        self.raw = raw
        self.nrows = raw["nrows"]
        self.frames = raw["frames"]
        self.bram_content_frames = raw["bram_content_frames"]
        self.frame_bytes = raw["frame_bytes"]
        self.preamble_frames = raw["preamble_frames"]
        self.overhead_bytes = raw["overhead_bytes"]
        self.per_cell = raw["per_cell"]
        self.columns = {int(k): v for k, v in raw["columns"].items()}
        self.pairs = {int(k): v for k, v in raw["pairs"].items()}
        self.specials = raw["specials"]
        self.totals = raw["totals"]
        self.xs = sorted(self.columns.keys())

    def cell_ok(self, c, r):
        """True if column c has fabric at clock-region row r."""
        return r in self.columns[c]["rows"]

    def col_type(self, c):
        return self.columns[c]["type"]

    def total_ramb18(self):
        return 2 * self.totals["ramb36"]


def _bundled_dir():
    if _res_files is not None:
        return _res_files(__package__) / "devices"
    return None


def list_devices():
    """Names of the device models bundled with the package."""
    d = _bundled_dir()
    if d is None:
        return []
    return sorted(p.name[:-5] for p in d.iterdir() if p.name.endswith(".json"))


def load_device(name_or_path):
    """Load a device model by bundled name (e.g. 'xc7z020') or JSON path."""
    if os.path.isfile(name_or_path):
        with open(name_or_path) as f:
            return Device(json.load(f))
    d = _bundled_dir()
    if d is not None:
        res = d / (name_or_path + ".json")
        if res.is_file():
            return Device(json.loads(res.read_text()))
    raise FileNotFoundError(
        "unknown device %r (bundled: %s; or pass a path to a device JSON)"
        % (name_or_path, ", ".join(list_devices()) or "none"))
