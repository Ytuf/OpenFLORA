# Changelog

## 0.2.0 (2026-11-23)

Partition-pin routability, special columns that cost a CLB column, and the
device model for other 7-series parts.

### Added

- **`pins` demand** (CSV column 7): a region's partition pins, one per bit of
  its ports.  Adds partition-pin sites as a resource in FLORA's Constraint 5
  form: pins <= pin_headroom x routing nodes of the region's
  module-routable interconnect tiles (99 per tile, probed).  It is exact,
  a necessary condition, at headroom 1.  README "Partition pins".
- **`out_pins` demand** (CSV column 8, optional): the region's output pins
  whose nets reach logic outside it.  Each needs a wire of its own leaving
  the region, so the solver keeps `out_pins` <= the one-way wires crossing
  the region's edge outward, with the long lines
  (`milp.out_pin_capacity`; on xc7z020 226 per interconnect column, top
  and bottom, plus 136 per interconnect row, the sides).  Exact, with no
  headroom: a necessary condition.  At most `pins` when both are given.
  It never binds on the measured regions (4.4 x or more their pins).
  README "Cuts".
- **`--pin-headroom`** (default 1.0, `milp.PIN_HEADROOM`: the exact bound).
  `milp.PIN_HEADROOM_MEASURED_42` = 0.0403 is the fraction of those sites
  Vivado 2019.1 used without failing on 42 regions of four designs built on
  xc7z020 (every port bit registered, wide register-file slots).  It is a
  value a caller may pass for designs like those, not a default.  It
  covers crowded pins only; pass-through wiring between pins Vivado places
  apart is not modeled (docs/LIMITS.md item 10).
- **Pin plans** (`emit.partpin_plan`, `--pin-plan [N] --pins-file F`): the
  XDC can place each region's partition pins (HD.PARTPIN_LOCS), each
  in/out pair in one interconnect tile, at most N a tile.  N defaults to 5,
  Vivado's own spreading target (PARTPIN_SPREADING).  `--pin-plan-trim R`
  (`trim`, default 0) optionally leaves R rows free at each edge.
  `emit.partpin_cut_demand` gives a fixed plan's exact cut demand by
  direction (0 for these plans), and `emit.partpin_cut_check` checks it
  against the one-way capacity.  No solver constraint changes with a plan.
- **Device model `routing` section** (probe section 5): routing wires,
  vertical and horizontal wire crossings and partition-pin wires per
  interconnect tile, interconnect tiles per cell, interconnect tile types,
  and the one-way crossings of a cut line (`one_way_crossings_per_tile`:
  north / south / either way, east / west / either way; xc7z020 83 / 83 /
  30 and 56 / 56 / 12).
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
- The demands CSV takes 5 to 8 fields.

### Unchanged

- A solve with no `pins` and no `out_pins` builds the same model as before
  apart from the x=33 correction (its capacity rows; byte-identical
  otherwise).
