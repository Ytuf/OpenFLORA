# Changelog

## 0.2.0 (proposed; not tagged)

Partition-pin routability, special columns that cost a CLB column, and the
device model for other 7-series parts.

### Added

- **`pins` demand** (CSV column 7): a region's partition pins, one per bit of
  its ports.  Adds partition-pin sites as a resource in FLORA's Constraint 5
  form: pins <= pin_headroom x routing nodes of the region's
  module-routable interconnect tiles (99 per tile, probed).  It is exact,
  a necessary condition, at headroom 1.  README "Partition pins".
- **`--pin-headroom`** (`milp.PIN_HEADROOM`, default 0.0403): the
  calibrated fraction of those sites Vivado 2019.1 used without failing,
  fitted on 42 regions of four designs built on xc7z020.  The calibration
  covers crowded pins only.  Pass-through wiring between pins Vivado
  places apart is not modeled (docs/LIMITS.md item 10).
- **Pin plans** (`emit.partpin_plan`, `--pin-plan N --pins-file F`): the
  XDC can place each region's partition pins (HD.PARTPIN_LOCS), each
  in/out pair in one interconnect tile, at most N a tile.
  `emit.partpin_cut_demand` gives a fixed plan's exact cut demand (0 for
  these plans).  No solver constraint changes with a plan.
- **Device model `routing` section** (probe section 5): routing wires,
  vertical and horizontal wire crossings and partition-pin wires per
  interconnect tile, interconnect tiles per cell, interconnect tile types.
- **`special_splits`** (`tools/probe_specials.py`, design-free): the CLB
  column whose placement Vivado prohibits while a region covers a given
  special column.
- **Other 7-series parts**: `probe_geometry.tcl -tclargs <part>`; probe
  section 6 (per-column, per-row site counts) lets the builder derive the
  rows and leave partly occluded cells out.  Checked on xc7z010 and
  xc7a35t; xc7z020 regenerates byte-identically.

### Changed

- A region covering xc7z020's x=33 no longer counts CLB column 32 (100
  SLICEL per clock-region row Vivado prohibits, [Constraints 18-993]).
  Solves whose regions cover x=33 can change; every recorded optimum in the
  test suite is unchanged.
- The demands CSV takes 5 to 7 fields.

### Unchanged

- A solve with no `pins` builds the same model as before apart from the
  x=33 correction (its capacity rows; byte-identical otherwise).
