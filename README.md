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

An optional seventh column, `pins`, is the region's partition-pin
count (the bit count of its ports); it adds the routability limits
described under "Partition pins" below.

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
reconfigurable partition's ports is a partition pin, and every pin is
routed into the region.  Without a model of that, OpenFLORA returned
floorplans that met every resource constraint and then failed in
Vivado: "N signals failed to route due to routing congestion", then
"[Constraints 18-1000] Routing results verification failed".  The
optional `pins` column of the demands CSV (the region's port bits)
adds two routability limits, built from facts measured on the real
part:

    name,lut,ff,bram,dsp,slices,pins
    rp0,446,1738,0,0,1000,1596

What the measurements showed (xc7z020, Vivado 2019.1, `get_pplocs` and
the routed nodes of routed and failed checkpoints):

* **A partition pin is a routing node inside the region (a PPLOC).**
  Vivado puts it on one of the 16 horizontal length-1 wires of an
  interconnect tile.  All 19,128 PPLOCs of twelve measured regions
  sat on those wires; only the regions too small for their pins (10
  slice cols x 1 row) spilled 7 % onto vertical singles.
* **The static design fixes the pins before any module is built.**  A
  slot's in-pin and out-pin land wherever the static logic wants them,
  sometimes tens of rows apart, and every module that passes the slot
  through wires between them.  How far apart they land grows with the
  height the pins spread over.  Vivado places them at about 2.9 per
  interconnect tile, so a narrow region spreads them over its whole
  height.
* **A special (site-less) column's interconnect stays static.**  It has
  no sites, so a site-range pblock cannot own it: no module route used
  `INT_R_X33` in the two routed regions that covered it, and its paired
  column took no pins.  BRAM and DSP columns' interconnect routes the
  module and takes pins.

The two limits, for a region with `tiles` interconnect tiles in `cols`
columns that route its module (CLB, BRAM and DSP columns, 50 tiles per
clock-region row):

| limit | constraint | what failed when it was exceeded |
|---|---|---|
| area | pins <= 0.2217 x 16 x tiles | 10 slice cols x 1 row: Vivado packed up to 20 pins into one interconnect-tile pair; most failing modules died on one node that two neighbouring pins both needed |
| width | pins x band <= 162.9 x 196 x cols | 8 slice cols x 3 rows: 42 of the 43 overlapping nodes were north-going vertical wires in the middle rows; 10 x 3 failed where the same columns routed at 10 x 2 |

band = min(region rows, pins / (2.9 x pin columns)): the rows the pins
spread over.  Pin columns are `cols` less the column paired with each
covered special column.

16 (partition-pin wires per tile) and 196 (vertical wire crossings per
tile column: the sum, over the tile's routing wires, of the
interconnect rows each one spans) come from the device.
`tools/probe_geometry.tcl` section 5 dumps every routing node of 174
sample interconnect tiles; `tools/build_device_model.py` reduces them
into the device model's `routing` section.  Three constants are
measured on builds:

* 2.9 pins per tile is Vivado's own packing, read directly from six
  regions (2.69-2.97);
* 0.2217 and 162.9 are each the density of the densest region that
  routed every module of the calibration design.  The failures lie
  above them.

The MILP takes the width limit as a disjunction with one binary per
region: either the band is the region's height and the height form
holds, or the pin columns reach pins / sqrt(2.9 x 162.9 x 196), which
makes the packed band fit.

The horizontal counterpart (vertical cut lines) is not modeled, because
it cannot bind on 7-series.  A region is at least one clock-region row
(50 tiles) high, so its vertical cut lines carry at least 50 x 124
wires.  The pin pairs crossing them were measured at the same few
hundred (281-426) as across horizontal cuts.

For CLB-only regions two clock-region rows high, the two limits are
the same as "slices >= pins / 1.77" and "slice columns >= pins / 160".
In one row the area limit binds first.  Where they differ:

* BRAM and DSP columns add routing width and pin area without adding
  slices; a special column adds neither;
* a region spanning three rows needs more columns unless its pins pack
  into a shorter band.

**What the constants rest on.**  The calibration design is RFP's GA at
33 modules: 1,596 pins per region, memory registers off.  Its modules
register every port bit, and the worst pass up to 89 % of the slot
bits straight through, which is what loads the width limit.  A design
whose modules pass fewer bits through is bounded conservatively.  Two
regions of the same shape can still differ:

* 8 x 3 failed in all three placements, by very different margins.
  At X82..X89, rm_18 left 43 overlapping nodes and rm_19 about 2,000.
  At X56..X63, rm_18 and rm_22 routed, and rm_19 left 9 nets in
  conflict;
* 10 x 1 failed in both its rows, through different nets.

Where the static design puts the pins is not known before
implementation, so the model is a shape-level bound.

Measured, per region (a region "routed" when all 33 modules routed in
it):

| region (slice cols x rows) | tiles | cols | band | area margin | width margin | measured |
|---|---|---|---|---|---|---|
| 22 x 1, X60Y0:X81Y49 | 550 | 11 | 50 | 1.22 | 4.40 | routed |
| 18 x 1, X36..X53 (rows 0 and 1) | 450 | 9 | 50 | **1.00** | 3.60 | routed |
| 14 x 3, X40Y0:X53Y149 | 1050 | 7 | 92 | 2.33 | 1.31 | routed |
| 14 x 3 + BRAM, X54Y0:X67Y149 | 1200 | 8 | 69 | 2.67 | 2.33 | routed |
| 12 x 2, X56Y50:X67Y149 | 600 | 6 | 92 | 1.33 | 1.31 | routed |
| 10 x 2, X44Y50:X53Y149 | 500 | 5 | 100 | 1.11 | **1.00** | routed |
| 8 x 3, X82..X89, X56..X63, X36..X43 | 600 | 4 | 138 | 1.33 | 0.58 | 2-9 of 33 failed |
| 10 x 1, X44..X53 (rows 0 and 1) | 250 | 5 | 50 | 0.56 | 2.00 | 9 of 33 failed |
| 10 x 3, X44Y0:X53Y149 | 750 | 5 | 138 | 1.67 | 0.67 | failed (rm_19, rm_27; see below) |

**Validation.**  Each prediction below was written down before the
region was built.

| region | model | "slices >= pins/1.77, slice cols >= pins/160" | measured |
|---|---|---|---|
| 14 slice cols + BRAM + 2 DSP x 1 row, X90Y50:X103Y99 | routes (area 1.11) | fails (700 slices) | routed 33 |
| 16 slice cols + BRAM + DSP x 1 row, X98Y0:X113Y49 | routes (area 1.11) | fails (800 slices) | routed 33 |
| 12 x 3, X56Y0:X67Y149 | routes (width 1.31: a 92-row band predicted; 111 measured) | routes | routed 33 |
| 10 x 3 + DSP, X92Y0:X101Y149 | routes (width 1.31) | routes | routed 33 |
| 8 slice cols + BRAM + DSP x 2 rows, X90Y50:X97Y149 | routes (width 1.31, area 1.33) | fails (800 slices, 8 slice cols) | 32 of 33 routed; rm_27 failed (20 signals, vertical wires) |
| 10 x 3, X44Y0:X53Y149 | **routes** (the first, height-blind model: width margin 1.00) | routes | **failed** |

The last row refuted the first version of the model, which bounded
width by columns alone.  Same columns as the 10 x 2 that routed, one
row taller: Vivado spread the pins over 137 rows instead of 100, and a
slot's in/out pins landed a median 47 rows apart instead of 9.  The
pin band is the model's answer to that.  The two 3-row, 6-column regions
above were built to test it.  The alternative fix, a lower width
density for every region spanning all three rows, predicted they fail.
They routed.

The 2-row BRAM + DSP region is the model's one miss.  The 12 x 2
region has the same margins and routed all 33.  The difference is
where the static design put the pins: a slot's in/out pair a median 27
rows apart in the BRAM + DSP region, 5 in the 12 x 2.  The miss was the single hardest module (it
passes 647 of its 723 slot bits straight through).  Of the six regions
with width margins of 1.0 to 1.31, five routed every module.  Treat a
width margin below ~1.3 as "usually routes", not as a guarantee.

The result dict reports, for a region with pins: `pins`, `pin_tiles`,
`pin_cols`, `pin_band`, and both margins (capacity / demand).  A solve
without `pins` builds exactly the model it always did: the HiGHS model
files are byte-identical to the previous release's.

## Other devices

`xc7z020` (the Zynq-7020 on the Pynq-Z2) ships bundled and fully
measured.  Adding a part is a recipe, not a code change: run
`tools/probe_geometry.tcl` against the part in Vivado (no design
needed), feed the output to `tools/build_device_model.py`, and pass the
resulting JSON to `--device`.  The geometry side is fully probe-derived.
The frame constants are 7-series values measured on xc7z020, so for
another device family re-measure them before trusting the `frames`
objective: generate two partials with known rectangles, run
`openflora parse-bit`, and solve for the per-column-type counts.  Notes
in `tools/build_device_model.py`.  The `routing` section (for the
`pins` demand) is probe-derived too; its three calibrated constants
were measured on xc7z020 with one design, so re-measure them on
another family before trusting the pin limits there.

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
in favor of the measured map.

## Tests

    pip install -e .[test]
    pytest

The suite pins the byte-exact reproduction of the measured partials
(sizes as fixtures; the bitstreams themselves are not shipped), the
emitter round-trip against the hand floorplan that ran on silicon, and
end-to-end solves on the bundled device model against the recorded
optima.  `tests/test_pins.py` pins the partition-pin model's verdict
on every region measured on the real part, routed or failed, and on
the validation regions.

## Contributing

Issues and PRs welcome.  The contributions worth the most are measured
ones: device models for new parts (run the probe recipe and open a PR
with the JSON plus the probe output), frame constants for other device
families, and reports of solved floorplans surviving — or not surviving
— place-and-route on real designs.  Two ground rules: don't copy or
translate code from the DART/FLORA repositories (this project stays
clean-room), and say how you measured any number you claim.

## References

If you use this in academic work, cite FLORA — the formulation is theirs
— and, if the frames objective matters to you, Vipin and Fahmy.

* B. B. Seyoum, A. Biondi, G. C. Buttazzo, *FLORA: FLoorplan Optimizer
  for Reconfigurable Areas in FPGAs*, CODES+ISSS / ESWEEK–TECS special
  issue, 2019.
  [PDF](https://retis.santannapisa.it/~a.biondi/papers/CODES19.pdf) ·
  [repository](https://github.com/biruk-belay/FLORA)
* B. Seyoum, M. Pagani, A. Biondi, G. Buttazzo, *Automating the design
  flow under dynamic partial reconfiguration for hardware-software
  co-design in FPGA SoC*, ACM SAC 2021, pp. 481–490.
  [repository](https://github.com/fred-framework/dart) ·
  [FRED docs](https://fred-framework-docs.readthedocs.io/)
* K. Vipin, S. A. Fahmy, *Architecture-Aware Reconfiguration-centric
  Floorplanning for Partial Reconfiguration*, Proc. 8th Int. Conf. on
  Reconfigurable Computing: Architectures, Tools and Applications
  (ARC 2012).
* AMD/Xilinx, *UG909: Vivado Design Suite User Guide — Dynamic Function
  eXchange (Partial Reconfiguration)*.
  [docs](https://docs.amd.com/r/en-US/ug909-vivado-partial-reconfiguration)
* AMD/Xilinx, *UG470: 7 Series FPGAs Configuration User Guide*.
  [docs](https://docs.amd.com/v/u/en-US/ug470_7Series_Config)
* *Project X-Ray* — public 7-series bitstream documentation.
  [repository](https://github.com/f4pga/prjxray)
* Q. Huangfu, J. A. J. Hall — *HiGHS*, the open-source LP/MIP solver
  this tool runs on.  [highs.dev](https://highs.dev) ·
  [repository](https://github.com/ERGO-Code/HiGHS)

## License

MIT.  See [LICENSE](LICENSE).