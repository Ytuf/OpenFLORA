# OpenFLORA

OpenFLORA is an MILP floorplanner for FPGA partial reconfiguration that
runs on an open solver.  You give it per-region resource demands and it
places each reconfigurable region as a legal rectangle on a measured
device model, then writes out pblock site ranges and Vivado XDC
constraints.  It can minimize FLORA's wasted-resources metric, or the
number of configuration frames — which is what your partial bitstream
size and your reconfiguration time are actually made of.

It is a clean-room reimplementation of FLORA's floorplanning
formulation, built from the published papers and public documentation
and MIT-licensed, solving with
[HiGHS](https://github.com/ERGO-Code/HiGHS) (also MIT) — nothing to
license, nothing to pin.

The motivation is licensing.  The published FLORA and DART
implementations solve with Gurobi, which is commercial (DART's install
docs pin Gurobi 8.1 and warn that later versions break the build), DART
itself is GPLv3, and the public FLORA repository has no license file at
all.  Floorplanning a partial-reconfiguration design shouldn't require a
commercial solver license.

## About the name

The name is an homage, not a fork.  FLORA (Seyoum, Biondi, and Buttazzo,
CODES+ISSS 2019) got the floorplanning problem right: a fine-grained
MILP over the real column structure of the fabric, with the vendor's
legality rules — back-to-back interconnect pairs, forbidden regions,
full clock-region height — as first-class constraints instead of
afterthoughts.  DART later built a full DPR design flow around it.
OpenFLORA is an independent, from-the-papers reimplementation and is not
affiliated with or endorsed by the FLORA/DART authors, their lab, or
AMD/Xilinx.  The name is meant to help people who already know FLORA
find a version they can run; anyone from the original projects who would
like to coordinate is welcome to reach out.

One note on capitalization: the project is OpenFLORA, but the Python
package and the command are plain lowercase `openflora`, following
Python packaging convention.

## Install

    pip install -e .

from a checkout.  That installs the library and the `openflora` command.
The only runtime dependency is `highspy`; Python 3.9 or newer.

## Using it

Describe your regions in a CSV, one row each.  The first five columns
follow the demand table in the FLORA paper — LUT, FF, BRAM (in RAMB18
units), DSP — and the optional sixth is measured occupied slices:

    name,lut,ff,bram,dsp,slices
    rp0,2874,2026,0,12,1127
    rp1,2972,2026,0,12,1264

An optional seventh column, `pins`, is the region's partition-pin count
(the bit count of its ports).  It adds the partition-pin site constraint
described under "Partition pins" below.  By default it is the exact
bound; `--pin-headroom` lets a caller pass a measured headroom instead.

Providing the measured `slices` column is strongly recommended.  Without
it the solver falls back to ceil(lut/4), which assumes perfect packing.
A placement failure on real hardware showed modules packing at 2.35–2.8
LUTs per slice, because a slice holds only one unique control set.  The
value can be obtained from `report_utilization -pblocks` on a routed
checkpoint ("Slice" row); `examples/lenet_pynq/README.md` walks through
the whole measurement recipe.

Then solve and emit constraints:

    openflora plan --csv demands.csv --device xc7z020 --objective frames \
        --static-bram 201 --out-pblocks pblocks.txt --out-xdc floorplan.xdc

`--objective` is `frames` or `wr` (FLORA's wasted-resources metric).
`--derate 0.5` is your own design-margin knob (0.5 = 2x headroom).
`--headroom` is a calibrated placement-headroom fraction, default 0.93,
multiplied with `--derate`; it absorbs what the flow itself eats between
the demand snapshot and a placed design (measured on the case study's
first hardware build: +1.1 % netlist growth, plus placer packing
limits).  `--static-bram N` reserves N RAMB18 for the static design,
`--forbid-specials` keeps regions off the clock-spine and config
columns, and `--cell rp0=path/to/inst` binds cells in the emitted XDC.
`--pin-plan N --pins-file pins.csv` also writes a partition-pin plan
into the XDC (README "Pin placement").
There is also `openflora parse-bit partial.bit`, which prints the
FAR/FDRI frame accounting of an existing 7-series partial bitstream.

A two-region xc7z020 instance solves to proven optimality in 0.2–7 s on
my laptop.

## The model, briefly

The bundled xc7z020 device model is measured, not transcribed: a Tcl
probe (`tools/probe_geometry.tcl`) dumps every fabric column, its type
and per-clock-region extent, the processor-subsystem occlusions, and the
per-row map of back-to-back interconnect pairs from the real part in
Vivado.

The MILP is FLORA's formulation restated with column-cover binaries:
rectangles on (column x clock-region) axes, per-type coverage >= demand,
region no-overlap, forbidden cells unspannable, interconnect pairs never
split, full clock-region height.  The restatement is equivalent at
device scale and makes per-cell frame costs exact.  Two additions extend
it: a static-BRAM reservation (the static design's memory has to live
outside the regions — an observed failure mode) and the frames objective
itself.

The frame model is byte-exact, measured by parsing real partial
bitstreams with a UG470 packet parser (the `parse-bit` subcommand).
Under RESET_AFTER_RECONFIG every covered frame is written twice, there
is a fixed 228-frame preamble, and bytes = 404 x frames + 452.  That
relation is exact on both parsed files (2,120 and 2,316 frames ->
856,932 and 936,116 bytes) and reconciles two more recorded partial
sizes to integer frame counts (3,064 / 2,700).  Per-column frame costs
(CLB 36, BRAM 28 plus 128 content frames, DSP 28, specials 30) were
pinned by four measured equations; Project X-Ray's public 7-series
documentation independently agrees on 101 words per frame and CLB = 36.

## Measured results

The validation case study is a LeNet-5 CNN accelerator that time-shares
two reconfigurable regions on a Pynq-Z2, written up in
`examples/lenet_pynq/`.  The baseline is a hand-drawn floorplan for the
same design, which ran on hardware; its two partial bitstreams parse
byte-exactly under the frame model.  With demands measured from the
routed checkpoints, the solved floorplans come out 30–42 % smaller at
the defaults:

| floorplan | partial bytes rp0/rp1 | vs. hand |
|---|---|---|
| hand (ran on silicon) | 856,932 / 936,116 (measured; model exact) | — |
| `frames` objective, defaults | 599,180 / 546,660 | −30.1 % / −41.6 % |
| `frames`, 2x margin (`--derate 0.5 --headroom 1.0`) | 987,828 / 1,108,220 | +15 % / +18 % |
| `frames`, `--forbid-specials` | 546,660 / 599,180 | −36 % / −36 % |

These results required several iterations of hardware validation.  The
first two attempts were wrong in ways only hardware could show.  The
first solved optimum (372,940 B) failed placement: the solver had put a
site-less clock-spine column at a pblock edge, site ranges cannot
express that, and the physical edge retracted mid-interconnect-pair, so
Vivado prohibited placement in both columns of the split pair
([Constraints 18-993], 100 SLICEL sites lost per region).  The fixes are
an edge-alignment hard constraint and the calibrated `--headroom`
default.  The second attempt (424,652 B) rebuilt with zero pair-split
warnings but failed detail placement on slice packing ([Place 30-487]:
~930 slices needed on a 900-slice pblock at only 72 % LUT utilization —
33 control sets, one unique control set per slice).  That failure is why
the demands CSV grew the measured `slices` column.  The third build went
through the whole flow: every configuration placed, routed, and met
timing; the rp1 partial came out byte-exact at 546,660 B and rp0 at
599,244 B — exactly the predicted 1,482 frames, plus 64 bytes of FAR
packet overhead where the 3-row region crosses the device's top/bottom
half boundary (a documented residual, `docs/LIMITS.md` item 6).

Round 4 was the board.  The solved-floorplan build executed twice on the
Pynq-Z2, every output word bit-exact against the application's oracle on
three independent readout channels, and execution time excluding
reconfiguration was unchanged within 5 µs of the hand-floorplan build —
the floorplan swap cost zero execution time.  Reconfiguration for the
application's 19 partial loads dropped from a measured 139.12 ms to a
measured 90.36 ms, −35.0 % (per-load: rp0 4.99 ms over 10 loads, rp1
4.50 ms over 9).  The flat-throughput projection, 88.9 ms at 122 MB/s,
landed 1.6 % under the measurement; the residual is a constant per-load
overhead that weighs relatively more on smaller partials.

The model does not cover timing at all, and it is honest about a few
other things it does not cover.  Read [`docs/LIMITS.md`](docs/LIMITS.md)
before trusting it on your design.

## Partition pins

A region that holds its logic can still fail to route: every bit of a
reconfigurable partition's ports is a partition pin, and every pin needs
a place inside the region.  The optional seventh CSV column, `pins` (the
region's port bits, clock excluded), adds one resource to FLORA's
formulation: partition-pin sites.

    name,lut,ff,bram,dsp,slices,pins
    rp0,446,1738,0,0,1000,1596

### The constraint, in FLORA's formulation

FLORA [1] describes the device by fingerprint functions f_t(x), the
resources of type t in one clock region within columns [0, x].  It
requires, for every region R_i and type t (its Constraint 5, with Eqs. 2
and 8):

    eta_{i,t} = sum_j beta_{i,j} * (f_t(x_i + w_i) - f_t(x_i)) >= c_{i,t},
    t in {CLB, BRAM, DSP}

OpenFLORA adds the type PIN:

    f_PIN(x) = N_w * T * (module-routable interconnect columns in [0, x])
    eps_P * eta_{i,PIN} >= c_{i,PIN}

* c_{i,PIN} is the region's `pins`.  It is the same for every module the
  region holds, since they share its interface.
* N_w = 99 is the routing nodes (wires) that begin in one interconnect
  tile: 32 singles, 32 doubles, 16 bent quads, 16 quads and 3 long lines.
  T = 50 is the interconnect tiles per clock-region row.  Both are
  probed from the part (`tools/probe_geometry.tcl` section 5, the device
  model's `routing` section).
* Module-routable columns are the CLB, BRAM and DSP columns.  A special
  (site-less) column's interconnect is left out.
* eps_P is the pin headroom.  Its default, 1, is the exact bound; a
  caller may pass a measured value (below).

OpenFLORA's MILP sums per-cell cover variables instead of FLORA's
linearized fingerprints; the sum is the same.

**Why the constraint is necessary at eps_P = 1.**  A region violating
`pins <= N_w x tiles` cannot hold its pins, whatever the placer and
router do:

1. Each partition pin is anchored on a routing node of an interconnect
   tile inside the region (its PPLOC).  UG909 places partition pins
   "within interconnect tiles" of the RP's Pblock ranges [7].  Every one
   of 19,128 PPLOCs measured in twelve regions was a single-length
   routing wire of the region's own interconnect.
2. No two pins share a node.  A node carries one net, and in 21,234
   measured pins across seven builds every pin had its own node.
3. A site-range Pblock owns the interconnect tiles of its site columns
   and none of a site-less column's.

N_w counts every routing node of the tile, a superset of the measured
PPLOC wires.  So the bound rests only on premises 1-3, not on which
wires Vivado prefers.

### Cuts: what can be derived, and what cannot

The device model also records the exact routing capacity of a cut line,
by direction, since 7-series wires are one-way
(`routing.one_way_crossings_per_tile`, from the probe's per-node spans).
On xc7z020:
* a horizontal cut line is crossed, per interconnect column, by 83 wires
  going north, 83 going south and 30 long-line crossings usable either
  way;
* a vertical cut line is crossed, per interconnect row, by 56 east, 56
  west and 12 either way.

So N nets forced north and S south across a horizontal line of c columns
fit only if max(N - 83c, 0) + max(S - 83c, 0) <= 30c, that is N, S <=
113c and N + S <= 196c.  The 196 sum alone overstates what either
direction can carry.  A cut constraint also
needs a demand that provably crosses the cut:

* **The region's boundary.**  Every output pin's static route, and every
  static net into the region, must cross it.  With only the pin count
  given, no useful lower bound follows: all input pins could share one
  static net.  OpenFLORA therefore adds no boundary constraint.  The
  wires that cross the boundary going inward numbered 3.5 x or more the
  pins of every measured region.
* **Interior cuts, Vivado placing the pins.**  There is no lower bound.
  A placement that puts each slot's in-pin and out-pin in one tile
  needs no pass-through wiring across any interior cut.  The static
  placer does split pairs (measured: a median 5-48 rows apart), and that
  is the second failure mechanism below.  It depends on Vivado's placer,
  not on anything the floorplanner controls, so it is **not modeled**
  (docs/LIMITS.md).
* **Interior cuts, with a fixed pin plan.**  The demand is exact, by
  direction.  `emit.partpin_cut_demand(plan, pairs)` counts, for each
  cut line, the (source, destination) pairs forced across it in each
  direction.  `emit.partpin_cut_check` tests those counts against the
  one-way capacity above.  OpenFLORA's own plans put each pair in one
  tile, so the demand is 0 (see "Pin placement").

### The pin headroom: exact by default, a measured value to pass

**The default is `--pin-headroom 1`** (`milp.PIN_HEADROOM`): the
provable bound above, which no device-independent tuning enters.

Vivado fails long before the sites run out: the crowded pins' routes
collide on a node that two neighbouring pins both need.  So OpenFLORA
also records a measured headroom that a caller may pass, like
`--headroom`, for designs like those it was measured on:

* **Measured value:** `--pin-headroom 0.0403`
  (`milp.PIN_HEADROOM_MEASURED_42`), that is 3.99 pins per interconnect
  tile.  It holds for designs like those below: every port bit
  registered, wide register-file slot interfaces, xc7z020, Vivado
  2019.1.  It is not a default.
* **Builds:** 42 regions on xc7z020 with Vivado 2019.1, in which Vivado
  placed the pins and every module was implemented in the region.  They
  cover four RFP designs: GA at budgets 666 (33 modules, 1,596 pins) and
  445 (46 modules, 2,050 pins), sobel at 200 (13 modules, 1,472 pins)
  and LeNet at 3000 (5 modules, 1,325 pins).
* **Verdict:** a region routed when every module routed in it.  The
  failures were located from the overlapping nodes of each failed
  module, and their mechanism attributed: "area" (crowded pins) or
  "width" (vertical wires across the middle rows).
* **Rule:** the densest region that routed every module, below the
  least-dense area failure.
  * Densest routed: GA b666 on an 8-column, 1-row region (BRAM + 7 CLB),
    1,596 / (400 x 99) = 0.0403.
  * Least-dense area failure: GA b445 on a 10-column, 1-row region,
    0.0414 (one module of 46).
  * The other area failures: GA b666 on 5 columns x 1 row, 0.0645.
* `tests/test_pins.py` re-derives the measured value from its table of
  all 42 regions.

The re-evaluation of every measured region, **at the measured headroom
0.0403**:

| design | pins | regions | accepted at 0.0403 | accepted, routed (0.0403) | accepted, failed: width (0.0403) | rejected, failed: area (0.0403) | rejected, routed (0.0403) | accepted at the default 1.0 (routed / failed) |
|---|---|---|---|---|---|---|---|---|
| GA b666 | 1596 | 30 | 28 | 21 | 7 | 2 | 0 | 30 (21 / 9) |
| GA b445 | 2050 | 4 | 3 | 3 | 0 | 1 | 0 | 4 (3 / 1) |
| sobel b200 | 1472 | 4 | 4 | 3 | 1 | 0 | 0 | 4 (3 / 1) |
| LeNet b3000 | 1325 | 4 | 3 | 3 | 0 | 0 | 1 | 4 (4 / 0) |
| all |  | 42 | 38 | 30 | 8 | 3 | 1 | 42 (31 / 11) |

* **All 8 accepted failures are width failures,** the mechanism not
  modeled.
* **No area failure is accepted.**  This is by construction of the rule,
  and the least-dense one (GA b445) was a held-out build.
* **The one rejected region that routed** is LeNet at 0.0446.

The same shape fails or routes depending on where the static design puts
the pins:

| design | routing columns x rows | placements | routed | failed (mechanism) | sites used |
|---|---|---|---|---|---|
| GA b666 | 4 x 3 | 3 | 0 | 3 (width) | 2.69% |
| GA b666 | 5 x 1 | 2 | 0 | 2 (area) | 6.45% |
| GA b666 | 6 x 2 | 10 | 7 | 3 (width) | 2.69% |
| GA b666 | 6 x 3 | 2 | 2 | 0 | 1.79% |
| GA b666 | 7 x 2 | 2 | 2 | 0 | 2.30% |
| GA b666 | 8 x 1 | 2 | 2 | 0 | 4.03% |
| GA b666 | 9 x 1 | 2 | 2 | 0 | 3.58% |
| GA b666 | 10 x 1 | 2 | 2 | 0 | 3.22% |
| sobel b200 | 4 x 3 | 2 | 1 | 1 (width) | 2.48% |
| LeNet b3000 | 4 x 3 | 2 | 2 | 0 | 2.23% |

The per-region table is in `ROUTABILITY_REPORT.md` and
`tests/test_pins.py`.  **At the default headroom (1, exact)** all 42
measured regions are accepted: the 31 that routed and all 11 that failed
(3 for crowded pins, 8 for width).  The exact bound rules out only
regions that cannot hold their pins at all.  The measured value is a
calibration on these builds.  It is not a promise that a region routes,
and other parts, Vivado versions or interface styles may need another
value.

### Pin placement

The static design fixes the pins before any module exists.  UG909's
remedy for congestion around them is to place them yourself
(HD.PARTPIN_LOCS, one interconnect tile per pin).  OpenFLORA can write
such a plan for the regions it returns:

    openflora plan --csv demands.csv --pin-plan 5 --pins-file pins.csv \
        --cell rp0=top/rp0_inst --cell rp1=top/rp1_inst --out-xdc fp.xdc

* `pins.csv` has one row per pin, `region,pin[,pair]`.  `pair` names
  the pin to put in the same tile, such as a slot's out-pin next to its
  in-pin.
* `emit.partpin_plan` spreads the pairs and single pins evenly over the
  region's pin tiles: every interconnect tile of a pin column, less one
  row at the top and bottom edge.  It puts at most N pins in a tile.
* With pairs co-located, the plan's interior cut demand from those pairs
  is 0, exactly (above).
* The solver sizes the regions the same way with or without a plan: no
  constraint changes.

Measured (GA b666):

| build | regions | pins | result |
|---|---|---|---|
| E1 | two 4-column, 3-row regions | pairs co-located, up to 8 a tile | 7 of 13 modules routed; modules that routed with Vivado's pins stopped converging (crowding) |
| E2 | the same | `partpin_plan`, at most 4 a tile (2.7 on average) | 12 of 16 routed, 5 of them modules that failed there with Vivado's pins; the 4 that combine heavy relaying with a memory read did not converge |
| E3 | two 1-row, 8-column regions | `partpin_plan`, at most 5 a tile (4.15 on average) | 33 of 33 in both |
| E3v | the same | Vivado's own | 33 of 33 in both |

Pairing removes the declared pairs' cut demand, and with it most of the
width failures in E2, but not the wiring of computed or memory bits.
Use a plan when a returned region fails for width: at most 4 or 5 a
tile, with the pairs co-located.  The head build must apply the XDC, and
every module then routes to the planned pins.

### Special columns that cost a CLB column

A site-less special column (a clock spine) has no sites, so a
site-range pblock cannot own its interconnect tile.  That splits the
tile's interconnect pair against static, and Vivado prohibits
placement in the pair's CLB column ([Constraints 18-993]).  On
xc7z020, a region covering x=33 loses CLB column 32 (100 SLICEL per
clock-region row; four GA builds), and covering x=50 costs nothing.
The device model's `special_splits` records this per special column,
and the solver leaves the lost column out of the region's slice
capacity and its pin columns (its interconnect still routes the
module).  `tools/probe_specials.py` measures `special_splits` without a
design: it places a one-cell design in a pair-aligned pblock around
each special column and reads the [Constraints 18-993] lines.

### How this relates to FLORA and the rest of the literature

The pin-site resource is OpenFLORA's addition: one more type in FLORA's
Constraint 5, on the same cover variables.  It leaves FLORA's
resources, legality rules and objectives untouched.  No published PR
floorplanner we found counts partition-pin sites or calibrates their
usable fraction.

* **FLORA** [1] counts the region-static communication logic as static
  and puts the wires between regions only into its wirelength
  objective.  It names region-I/O wirelength and aspect ratio as
  possible further metrics.
* **DART** [2] parses Vivado's error after implementation and, for
  resource errors, raises the margin and runs again.  It adds snapping
  rules (an extra CLB margin; no region edge right next to a BRAM or DSP
  column).
* **Vipin and Fahmy** [3] keep I/O in static.  Their survey [6] notes
  that static wires through a region congest it, and that "even two PRRs
  with identical sizes and resources may have different routing to the
  static region depending on their relative positions": the shape table
  above shows it.
* **PRFloor** [4] (the PlanAhead proxy-LUT flow) states that "the number
  of CLBs along the edges of the PRRs should be large enough to avoid
  routing congestion", without a number.
* **PR-ESP** [5] adapts FLORA with a fixed accelerator-socket interface
  and adds no routability constraint.
* **UG909** [7] ("Partition Pin Placement") says the placer "attempts to
  spread the partition pins, minimizing the number of partition pins per
  interconnect along the edges, and increasing the PartPin density
  towards the middle of the Pblock".  A custom range must be "wide
  enough to allow for spreading, or you are likely to see congestion
  around the PartPins", and "for timing-critical interface signals or
  designs with high congestion, it might be necessary to help guide the
  placement of the PartPins".  The area failures agree: Vivado packed
  up to 15 pins into a tile there, against its spreading target of 5
  (PARTPIN_SPREADING, default in 2019.1, read with `report_property`).

## Other devices

`xc7z020` (the Zynq-7020 on the Pynq-Z2) ships bundled and fully
measured.  Adding a 7-series part is a recipe, not a code change:

1. `vivado -mode batch -source tools/probe_geometry.tcl -tclargs <part>`
   (no design needed) writes the part's geometry: site columns,
   per-row site counts (section 6, which lets the builder derive the
   clock-region rows and leave partly occluded cells out) and the
   interconnect inventory (section 5).
2. `python tools/build_device_model.py <probe output> model.json`
   builds a first device model.
3. `python tools/probe_specials.py model.json <part> > probe_specials.tcl`,
   then `vivado -mode batch -log probe_specials.log -source
   probe_specials.tcl`, measures which CLB column each special column
   costs a region that covers it.  This step needs no user design.
4. `python tools/build_device_model.py <probe output> model.json
   --specials probe_specials.log` adds `special_splits`; pass the JSON
   to `--device`.

The geometry, the `routing` section and `special_splits` are all
probe-derived.  The probe and the builder were run on xc7z010 and
xc7a35t as well as xc7z020; the routing facts per interconnect tile
(16 partition-pin wires, 196 vertical and 124 horizontal crossings, 50
tiles per clock-region row) came out the same on all three, and the
bundled xc7z020 model regenerates byte for byte.  Two kinds of
constant are measured on builds, not probed, and were measured on
xc7z020 only:

* the frame constants: re-measure them for another family before
  trusting the `frames` objective.  Generate two partials with known
  rectangles, run `openflora parse-bit`, and solve for the
  per-column-type counts (notes in `tools/build_device_model.py`);
* the measured pin headroom (0.0403, passed with `--pin-headroom`): it
  rests on Vivado 2019.1's pin placer and router on xc7z020 and on the
  measured designs.  The default (1) is exact on any part, because the
  site count it scales is probed.  For a measured value on another
  family, Vivado version or design style, re-run the measurement (README
  "The pin headroom").

## Provenance

OpenFLORA is a clean-room implementation, developed from published
literature and public documentation: FLORA's formulation and rules,
frame-count minimization in the lineage of Vipin and Fahmy's
reconfiguration-centric floorplanning, and Xilinx's own guides (UG909
for the partial-reconfiguration rules, UG470 for the configuration
packet and frame format).  No source code from DART or FLORA was used or
consulted; their repositories are referenced in prose only.  Device
models and frame costs are measurement-based — Vivado geometry probes of
the real part and byte-exact parses of partial bitstreams.  Published
numeric device facts from the original authors were used only as an
after-the-fact cross-check, and the single divergence found was resolved
in favor of the measured map.  The partition-pin site count is probed
the same way.  Its semantics (PPLOCs, HD.PARTPIN_LOCS) are UG909's.  Its
default is the exact bound.  The measured pin headroom a caller may
pass is fitted to the builds listed under "Partition pins".

## Tests

    pip install -e .[test]
    pytest

The suite pins the byte-exact reproduction of the measured partials
(sizes as fixtures; the bitstreams themselves are not shipped), the
emitter round-trip against the hand floorplan that ran on silicon, and
end-to-end solves on the bundled device model against the recorded
optima.  `tests/test_pins.py` pins the partition-pin model's verdict
on every region measured on the real part, routed or failed, across
four designs.  It checks that the default is the exact bound, and
re-derives the measured pin headroom from that table.
`tests/test_pin_plan.py` covers the pin plans, their exact cut demand
and their CLI.

## Contributing

Issues and PRs welcome.  The contributions worth the most are measured
ones: device models for new parts (run the probe recipe and open a PR
with the JSON plus the probe output), frame constants for other device
families, and reports of solved floorplans surviving — or not surviving
— place-and-route on real designs.  Two ground rules: don't copy or
translate code from the DART/FLORA repositories (this project stays
clean-room), and say how you measured any number you claim.

## References

If you use this in academic work, cite FLORA [1] -- the formulation is
theirs -- and, if the frames objective matters to you, Vipin and Fahmy
[3].  The partition-pin site resource, its headroom, pin plans and
`special_splits` are OpenFLORA's own additions, not part of FLORA's
formulation; [4]-[7] are the related work they were checked against
("How this relates to FLORA and the rest of the literature").

1. B. B. Seyoum, A. Biondi, G. C. Buttazzo, *FLORA: FLoorplan Optimizer
   for Reconfigurable Areas in FPGAs*, ACM Transactions on Embedded
   Computing Systems 18(5s), 2019 (CODES+ISSS / ESWEEK-TECS special
   issue).  doi:10.1145/3358202 ·
   [PDF](https://retis.santannapisa.it/~a.biondi/papers/CODES19.pdf) ·
   [repository](https://github.com/biruk-belay/FLORA)
2. B. Seyoum, M. Pagani, A. Biondi, G. Buttazzo, *Automating the design
   flow under dynamic partial reconfiguration for hardware-software
   co-design in FPGA SoC*, ACM SAC 2021, pp. 481-490.
   doi:10.1145/3412841.3441928 ·
   [repository](https://github.com/fred-framework/dart) ·
   [FRED docs](https://fred-framework-docs.readthedocs.io/)
3. K. Vipin, S. A. Fahmy, *Architecture-Aware Reconfiguration-centric
   Floorplanning for Partial Reconfiguration*, Proc. 8th Int. Symp. on
   Applied Reconfigurable Computing (ARC 2012), LNCS 7199, pp. 13-25.
4. T. D. A. Nguyen, A. Kumar, *PRFloor: An Automatic Floorplanner for
   Partially Reconfigurable FPGA Systems*, ACM/SIGDA FPGA 2016.
   doi:10.1145/2847263.2847270
5. B. Seyoum, D. Giri, K.-L. Chiu, B. Natter, L. P. Carloni, *PR-ESP: An
   Open-Source Platform for Design and Programming of Partially
   Reconfigurable SoCs*, DATE 2023.
6. K. Vipin, S. A. Fahmy, *FPGA Dynamic and Partial Reconfiguration: A
   Survey of Architectures, Methods, and Applications*, ACM Computing
   Surveys 51(4), article 72, 2018.  doi:10.1145/3193827
7. AMD/Xilinx, *UG909: Vivado Design Suite User Guide -- Dynamic Function
   eXchange (Partial Reconfiguration)*, section "Partition Pin
   Placement" (quoted from the 2023.1 edition; measured behavior from
   Vivado 2019.1).
   [docs](https://docs.amd.com/r/2023.1-English/ug909-vivado-partial-reconfiguration/Partition-Pin-Placement)
8. AMD/Xilinx, *UG470: 7 Series FPGAs Configuration User Guide*.
   [docs](https://docs.amd.com/v/u/en-US/ug470_7Series_Config)
9. *Project X-Ray* -- public 7-series bitstream documentation.
   [repository](https://github.com/f4pga/prjxray)
10. Q. Huangfu, J. A. J. Hall -- *HiGHS*, the open-source LP/MIP solver
    this tool runs on.  [highs.dev](https://highs.dev) ·
    [repository](https://github.com/ERGO-Code/HiGHS)

## License

MIT.  See [LICENSE](LICENSE).