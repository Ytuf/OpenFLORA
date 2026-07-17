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
in `tools/build_device_model.py`.

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
optima.

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