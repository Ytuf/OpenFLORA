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

Two optional columns add the routability limits described under
"Partition pins" below: a seventh, `pins`, the region's partition-pin
count (the bit count of its ports), and an eighth, `passthrough`, the
most output bits any of its modules takes from an input pin (the worst
case, ceil(pins / 2), when absent).

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

## Partition pins (routability)

A region that holds its logic can still fail to route.  Every bit of a
reconfigurable partition's ports is a partition pin, and Vivado routes
every pin into the region.  Without a model of that, OpenFLORA returned
floorplans that met every resource constraint and then failed in Vivado
with "N signals failed to route due to routing congestion" and
"[Constraints 18-1000] Routing results verification failed".

The optional `pins` and `passthrough` columns of the demands CSV turn on
three routability limits, built from facts measured on the real part:

    name,lut,ff,bram,dsp,slices,pins,passthrough
    rp0,446,1738,0,0,1000,1596,648

* `pins`: the region's partition pins, the bit count of its ports (clock
  excluded).
* `passthrough`: the most output bits any one module of the region takes
  from an input pin, either copied or computed.  When absent, the worst
  case is assumed: every output bit, ceil(pins / 2).

### What limits a region

Both mechanisms were found by locating the overlapping nodes of failed
routes (xc7z020, Vivado 2019.1).

1. **Pin crowding (area).**  A partition pin is a routing node inside the
   region (a PPLOC) on one of the 16 horizontal length-1 wires of an
   interconnect tile.  All 19,128 PPLOCs of twelve measured regions sat on
   those wires.  Vivado aims at PARTPIN_SPREADING pins per tile (default 5).
   In a region with too few tiles it packs up to 15, the only case that
   spilled onto vertical singles, and the routes out of neighbouring pins
   collide.  Every module whose route failed this way died on a single node
   that two neighbouring pins both needed.
2. **Pass-through wiring (width).**  The static design fixes every pin
   before any module is built, so a slot's in-pin and out-pin can land tens
   of rows apart.  A module that passes the slot through wires between
   them, across the region's horizontal cut lines, which carry 196 wires per
   interconnect column.  In a narrow region Vivado spreads the pins over
   the whole height, and the north-going (or south-going) wires of the
   middle rows run out: 42 of 43 overlapping nodes in one failure, 747 of
   919 routing-wire overlaps in another.  On an 8 slice col x 3 row region,
   every module passing 615 or more bits through failed and every one
   passing 484 or fewer routed.

### The limits

For a region with `tiles` interconnect tiles in `cols` columns that route
its module (CLB, BRAM and DSP columns, 50 tiles per clock-region row):

| limit | constraint |
|---|---|
| area | pins <= AREA x 16 x tiles |
| width | passthrough x band <= WIDTH x 196 x cols |
| height | passthrough x cols <= WIDTH x 124 x rows (in interconnect rows) |

* band = min(region rows, pins / (2.9 x pin columns)) is the rows the pins
  spread over.  Pin columns are `cols` less the CLB columns covered special
  columns cost (below).
* 16 (partition-pin wires per tile), 196 and 124 (vertical and horizontal
  wire crossings per tile, measured from the spans of the tile's routing
  wires) and 50 come from the device: `tools/probe_geometry.tcl` section 5,
  reduced by `tools/build_device_model.py` into the device model's
  `routing` section.  They are the same on xc7z010, xc7z020 and xc7a35t.
* 2.9 is Vivado's own packing, read directly from six regions (2.69-2.97
  pins per used tile).
* AREA = 0.2494 and WIDTH = 43.32 are the fitted densities (next
  section).

The MILP takes the width limit as a disjunction with one binary per
region.  Either the band is the region's height, or the pins pack into
a shorter band, which holds when pin columns x cols >= passthrough x
pins / (2.9 x WIDTH x 196).  That product is linearized exactly: with
s = cols - pin columns (an integer), the bound on pin columns is convex
in s, and one tangent cut per integer s makes it exact at every one.

The height limit is the width limit turned 90 degrees, with the same
density and the pins' horizontal spread bounded by the region's width.
No measured region came near it: the most pin pairs measured across a
vertical cut line was 472, against capacities of thousands.  For a
region at its area capacity with the worst-case pass-through, it binds
beyond sqrt(WIDTH x 124 / (8 x AREA)) = 51.9 routing columns: on xc7z020,
only a 1-row region spanning most of the part with about 10,200 pins.
It is modeled so that such regions and larger parts stay bounded, and
it is unvalidated.

### The pass-through input

The width limit scales with the pass-through bits, and that is the
input that separates the designs.  LeNet's modules take at most 133 of
their output bits from an input pin; GA's take up to 648 (most of them
copied slot bits).  LeNet routed every module in 4-column, 3-row
regions where GA's heaviest modules failed.

To compute it for a design: for each module the region holds, count
the output port bits whose logic cone reaches an input port bit,
registered or not, and take the most of any module.  For RFP's modules
it is the relayed plus the computed slot bits.  When it is not known,
leave the column out.  The worst case is then assumed (every output
bit, ceil(pins / 2)), which is never optimistic.

Is more input needed?  The scatter below is not explained by anything
known before the static design is implemented.  Measured from the
static design's own pin placements (`get_pplocs`):

* the failed GA region (6 cols x 2 rows) had its slot pairs a mean 30
  rows apart, with 61 pairs per column across its busiest cut;
* a GA region of the same width density that routed had them 32 rows
  apart, with 66-69 per column;
* sobel's routed and failed 4 x 3 regions had 109 and 103 pairs per
  column across their busiest cut.

The pin placement is a product of the static implementation, so no
floorplanner input can supply it.  A pin plan fixes it instead (below).

### Calibration and the guarantee

The two densities come from one rule, applied jointly to every region
built with Vivado placing the pins: 40 regions of four RFP designs
(xc7z020, Vivado 2019.1).  Each is the density of the densest region
that routed every module, below the least-dense failure of that limit's
mechanism:

* AREA = 0.2494: GA b666's 1,596 pins on an 8-column, 1-row region's
  400 tiles.  The least-dense area failure: GA b445 at 0.256 (one
  module of 46 failed).
* WIDTH = 43.32: GA b666's 648 pass-through bits over a 91.7-row band
  on a 7-column, 3-row region.  The least-dense width failure: GA b666
  at 50.5.

So no measured failure is accepted.  `tests/test_pins.py` re-derives
both densities from its table of the measured regions.

**What OpenFLORA promises.**  A region it returns is no denser, in
either limit, than regions that routed every module on the real part.
Every one of the 17 measured regions the model accepts routed, and
12 of them were built after a prediction was recorded.  It is an
empirical promise, not a proof.  Once the model had its final form
(the pass-through input and the exact solver), 9 regions were predicted
to route under the constants then in force, and 8 routed.  The ninth, GA
b445 at 0.93 x the area constant then in force (0.2760), failed one
module of 46, and the rule lowered the area constant below it.

**Why no further margin.**  The same shape at the same density routes
or fails depending on where the static design puts the pins:

| design | width density | x the constant | area density | placements | routed | failed (mechanism) |
|---|---|---|---|---|---|---|
| GA b666 | 16.5 | 0.38 | 0.200 | 2 | 2 | 0 |
| GA b666 | 18.4 | 0.42 | 0.222 | 2 | 2 | 0 |
| LeNet b3000 | 19.4 | 0.45 | 0.138 | 2 | 2 | 0 |
| GA b666 | 20.7 | 0.48 | 0.249 | 2 | 2 | 0 |
| GA b666 | 33.1 | 0.76 | 0.399 | 2 | 0 | 2 (area) |
| GA b666 | 43.3 | 1.00 | 0.095/0.142 | 3 | 3 | 0 |
| GA b666 | 50.5 | 1.17 | 0.111/0.166 | 10 | 8 | 2 (width) |
| sobel b200 | 94.8 | 2.19 | 0.153 | 2 | 1 | 1 (width) |
| GA b666 | 113.7 | 2.62 | 0.166 | 3 | 0 | 3 (width) |

Failures were measured from 1.03 x the area constant and 1.17 x the
width constant.  At 1.17 x the width constant, 2 of 10
placements failed.  The constants sit below every measured failure.  A
further derate would be a number with no measurement behind it.

Per design (the full per-region table is in `tests/test_pins.py`):

| design | pins | pass-through | regions | accepted (all routed) | of them predicted before the build | failures (all rejected) | routed but rejected |
|---|---|---|---|---|---|---|---|
| GA b666 | 1596 | 648 | 28 | 11 | 6 | 8 | 9 |
| GA b445 | 2050 | 809 | 4 | 1 | 1 | 1 | 2 |
| sobel b200 | 1472 | 586 | 4 | 2 | 2 | 1 | 1 |
| LeNet b3000 | 1325 | 133 | 4 | 3 | 3 | 0 | 1 |
| all | | | 40 | 17 | 12 | 10 | 13 |

### Pin placement

The static design fixes the pins before any module exists, and where
it puts them is the scatter above.  UG909's remedy is to place them
yourself (HD.PARTPIN_LOCS, one interconnect tile per pin).  OpenFLORA
can write such a plan for the regions it returns:

    openflora plan --csv demands.csv --pin-plan 5 --pins-file pins.csv \
        --cell rp0=top/rp0_inst --cell rp1=top/rp1_inst --out-xdc fp.xdc

`pins.csv` has one row per partition pin, `region,pin[,pair]`.  `pair`
names the pin to put in the same interconnect tile, such as a slot's
out-pin next to its in-pin.  `emit.partpin_plan` spreads the pairs and
single pins evenly over the region's pin tiles: every interconnect tile
of a pin column, less one row at the region's top and bottom edge.  It
puts at most N pins in a tile, and the XDC gains one
`set_property HD.PARTPIN_LOCS` line per pin.

**The solver does not count on the plan.**  It sizes the regions by the
limits above, as if Vivado placed the pins.  The pin-plan builds
(GA b666) are the reason:

| build | regions | pins | result |
|---|---|---|---|
| E1 | two 4-column, 3-row regions (8 slice cols x 3) | pairs in one tile, up to 8 a tile | 7 of 13 modules routed; modules that routed easily with Vivado's pins stopped converging (crowding) |
| E2 | the same | `partpin_plan`, at most 4 a tile (2.7 on average) | 12 of 16 routed, 5 of them modules that failed there with Vivado's pins; the 4 that combine heavy relaying with a memory read did not converge |
| E3 | two 1-row, 8-column regions (BRAM + 7 CLB; BRAM + DSP + 6 CLB) | `partpin_plan`, at most 5 a tile (4.15 on average) | all 33 routed in both |
| E3v | the same | Vivado's own | all 33 routed in both, as the model predicted (area margin 1.11) |

* Within the limits, Vivado's own placement was enough.  E3's regions
  routed without the plan (E3v), so the plan has no area gain to
  credit.
* Pairing relieves the width limit's cause.  In E2, five modules that
  failed with Vivado's pins routed with the plan, but four did not.  How
  much it relieves was not measured, so it earns no width credit.
* Dense pairing is harmful: up to 8 a tile (E1) failed.

Use it when a region fails on location, the scatter the limits leave
room for.  A plan of at most 4 or 5 a tile, pairing each slot's pins,
is the measured remedy worth trying.  It is not a guarantee.  The head
build must apply the XDC, and every module then routes to the planned
pins.

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

No published PR floorplanner we found models partition-pin
routability quantitatively, and the limits above are OpenFLORA's own
extension; they are not part of FLORA's formulation.  They add
per-region constraints on FLORA's column and row cover variables and
leave its resources, legality rules and objectives untouched.

* **FLORA** [1] counts the region-static communication logic as static
  and puts the wires between regions only into its wirelength
  objective.  It has no routability constraint, and it names aspect
  ratio and region-I/O wirelength as possible further metrics.  The pin
  limits extend FLORA in that direction; they do not contradict it.
* **DART** [2] parses Vivado's error after implementation and, for
  resource errors, raises the margin and runs again.  It adds snapping
  rules (an extra CLB margin; no region edge right next to a BRAM or
  DSP column).  OpenFLORA instead sizes the region before
  implementation so that the measured failure mechanisms do not occur.
* **Vipin and Fahmy** [3] keep I/O in static and count wirelength as
  Manhattan distance times wires.  Their survey [6] states that static
  wires through a region congest it and that "even two PRRs with
  identical sizes and resources may have different routing to the
  static region depending on their relative positions".  The location
  scatter measured here (below) agrees.
* **PRFloor** [4] (the PlanAhead proxy-LUT flow) states that "the number
  of CLBs along the edges of the PRRs should be large enough to avoid
  routing congestion", without a number.  The area and width limits are
  measured versions of that rule for Vivado's partition pins.
* **PR-ESP** [5] adapts FLORA with a fixed accelerator-socket interface
  and adds no routability constraint.
* **UG909** [7] ("Partition Pin Placement") says the placer "attempts
  to spread the partition pins, minimizing the number of partition pins
  per interconnect along the edges, and increasing the PartPin density
  towards the middle of the Pblock".  It warns that a custom
  HD.PARTPIN_RANGE must be "wide enough to allow for spreading, or you
  are likely to see congestion around the PartPins", and that "for
  timing-critical interface signals or designs with high congestion, it
  might be necessary to help guide the placement of the PartPins".  It
  gives no capacity rule.  The measurements agree and put numbers on
  it: the regions that failed for area are those where Vivado packed
  beyond its spreading target (the Pblock property PARTPIN_SPREADING,
  5 pins a tile by default in 2019.1, read with `report_property`), up
  to 15 pins a tile.  "Pin placement" above is the "guide the placement"
  remedy, measured.

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
* the partition-pin densities (AREA, WIDTH, 2.9 and the plan density):
  they rest on Vivado 2019.1's pin placer and router on xc7z020.  On
  another 7-series part with the same interconnect they are a
  reasonable start.  On another family, or another Vivado version,
  re-run the calibration (README "Calibration and the guarantee").

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
in favor of the measured map.  The partition-pin limits are measured
the same way, on Vivado builds of the real part.  Their semantics
(PPLOCs, HD.PARTPIN_LOCS, PARTPIN_SPREADING) are UG909's, and their
constants are fitted to the builds listed under "Partition pins".

## Tests

    pip install -e .[test]
    pytest

The suite pins the byte-exact reproduction of the measured partials
(sizes as fixtures; the bitstreams themselves are not shipped), the
emitter round-trip against the hand floorplan that ran on silicon, and
end-to-end solves on the bundled device model against the recorded
optima.  `tests/test_pins.py` pins the partition-pin model's verdict
on every region measured on the real part, routed or failed, across
four designs, and re-derives the two fitted densities from that table;
`tests/test_pin_plan.py` covers the pass-through input, the pin plans
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
[3].  The partition-pin model, the pass-through input, pin plans and
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