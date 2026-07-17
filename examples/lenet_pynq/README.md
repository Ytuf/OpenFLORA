# Case study: a LeNet-5 accelerator on two reconfigurable regions (Pynq-Z2)

This is the design the tool was validated on: a LeNet-5 CNN inference
accelerator that time-shares two reconfigurable regions on a Pynq-Z2
(xc7z020), built with Vivado 2019.1 and run on silicon.  The two regions
alternate — while one computes, the other is reconfigured with the next
piece of the network — so a single inference performs 19 partial loads.
Its hand-drawn floorplan is the measured baseline; the two partial
bitstreams that floorplan produced were parsed byte-exactly and are the
source of the tool's frame model.

## Inputs

`demands.csv` — per-region demands, the component-wise max over the four
configurations' post-route utilization reports (rp0_inst / rp1_inst rows).
The `slices` column is the measured occupied-slice max over the same four
routed checkpoints (`report_utilization -pblocks`, "Slice" row), added
after the round-2 placement failure showed LUT/FF coverage alone
under-models slice packing:

| region | LUT | FF | BRAM (RAMB18) | DSP | slices (occupied) |
|---|---|---|---|---|---|
| rp0 | 2,874 | 2,026 | 0 | 12 | 1,127 |
| rp1 | 2,972 | 2,026 | 0 | 12 | 1,264 |

The binding module in both regions is the same one (33 control sets,
2,026 FFs); as routed it packs at 2.35 LUTs/slice, not the 4 LUTs/slice a
LUT-only model implies.  The static design needs 100 RAMB36 + 1 RAMB18 =
201 RAMB18, all outside the regions — hence `--static-bram 201`.

## Measuring demands from your own design

Nothing in `demands.csv` is specific to this design's tool flow; any
Vivado DFX project can produce the same table.

1. For each configuration, open the routed checkpoint and run
   `report_utilization -pblocks [get_pblocks]`.  The per-pblock section
   gives the LUTs, FFs, RAMB36/RAMB18, and DSPs placed inside the
   region; the "Slice" row gives occupied slices.
2. A region's demand is the component-wise maximum over every module
   that can be loaded into it — the same rule the FLORA paper states for
   its demand vectors.  Take the max across all configurations, per
   region, per column.
3. Convert BRAM to RAMB18 units: `bram = 2 * RAMB36 + RAMB18`.
4. No routed floorplanned design yet (the usual chicken-and-egg — you
   are here to make one)?  Start from per-module
   `report_utilization -hierarchical` on the synthesized netlists for
   LUT/FF/BRAM/DSP and leave `slices` blank, but treat the result as
   optimistic and keep margin: hierarchical reports carry no slice
   occupancy, and the ceil(lut/4) fallback is a perfect-packing floor.
   `report_control_sets -verbose` shows how control-set-rich a module
   is, which is exactly what pushes real slice occupancy past that
   floor (a slice holds only one unique control set).

## Reproduce

```
openflora plan --csv demands.csv --device xc7z020 --objective frames \
    --static-bram 201 --out-pblocks expected_pblocks.txt --out-json expected_result.json

# sensitivity rows (--headroom 1.0 isolates the geometry knobs from the
# calibrated placement margin, which defaults to 0.93):
openflora plan --csv demands.csv --device xc7z020 --objective frames --static-bram 201 --derate 0.5 --headroom 1.0
openflora plan --csv demands.csv --device xc7z020 --objective frames --static-bram 201 --forbid-specials
openflora plan --csv demands.csv --device xc7z020 --objective wr     --static-bram 201 --headroom 1.0
```

`expected_pblocks.txt` / `expected_result.json` are the committed outputs of
the first command.  Note: at this size several optimal solutions differ only
in WHERE the rectangles land; the frame counts and byte sizes below are the
proven optimum and are stable, the placement among equivalent spots is
solver-arbitrary (the regression tests assert the invariants, not the spots).

## Results (measured baseline vs. solved floorplans)

All solver runs reach proven optimality in 0.2–7 s on a laptop.

| floorplan | rp0 ranges | rp1 ranges | frames rp0/rp1 | partial bytes rp0/rp1 |
|---|---|---|---|---|
| **hand (ran on silicon)** | SLICE_X0Y0:X31Y49 + DSP48_X0-X1 + RAMB36_X0-X1 (tiles 2..21, row 0) | SLICE_X56Y0:X101Y49 + DSP48_X3 + RAMB36_X4 (tiles 38..63, row 0) | 2,120 / 2,316 | **856,932 / 936,116 (measured; model exact)** |
| **frames objective (defaults)** | 5 CLB + 1 DSP cols x 3 rows (e.g. tiles 58..63) | 7 CLB + 1 DSP cols x 2 rows (e.g. tiles 24..31) | 1,482 / 1,352 | **599,180 / 546,660 (−30.1 % / −41.6 %)** |
| **wr objective (FLORA's metric), `--headroom 1.0`** | 12 CLB + DSP + BRAM cols, one row | 13 CLB + DSP + BRAM cols, one row | 1,464 / 1,596 | 591,908 / 645,236 |
| frames, 2x margin (`--derate 0.5 --headroom 1.0`) | 28 cols x 1 row | 12 cols x 3 rows | 2,444 / 2,742 | 987,828 / 1,108,220 (+15 % / +18 % — 2x margin on the measured slice demand costs real area) |
| frames, `--forbid-specials` | 8 cols x 2 rows | 6 cols x 3 rows | 1,352 / 1,482 | 546,660 / 599,180 (−36 % / −36 %) |

(Two earlier revisions of this table showed a 922-frame / 372,940-byte
optimum and then a 1,050-frame / 424,652-byte optimum.  Both **failed
placement on hardware** — see "Hardware validation" below — and the model
now excludes both by construction: the first via the edge-alignment
constraint, the second via the measured `slices` demand.)

With the measured slice demands the two regions' optima differ (1,127 vs
1,264 occupied slices), and the per-region spots can swap between
equivalent-total solutions — the regression tests assert the multiset of
per-region frame counts.  The wr objective now covers a BRAM column in
each single-row span (its long spans cannot reach a DSP column without
crossing one); the frames objective refuses BRAM columns (28+128 content
frames per row against 36 for CLB — 4.3x) and goes multi-row instead.
That split remains the concrete argument for the frames objective:
**wasted resources is only a proxy; when they disagree, frames is the one
aligned with reconfiguration time.**

## Reconfiguration time: projection vs. measurement

The configuration-port throughput was measured at two silicon points on
this platform (9.528 ms / 1.165 MB and 7.32 ms / 0.897 MB — 122.2 and
122.5 MB/s: linear, no measurable fixed cost).  The application loads 19
partials per run with 37.07 ms of compute.  The projection row below was
written before the round-4 board run; the measured row is that run (see
"Hardware validation", round 4):

| floorplan | avg partial | per load | 19 loads | wall | reconfig share |
|---|---|---|---|---|---|
| hand (measured on silicon) | 896,524 B | 7.32 ms | 139.12 ms | 176.19 ms | 79 % |
| frames objective, projected | 572,920 B | 4.68 ms | 88.9 ms | ~126.0 ms | ~71 % |
| frames objective, **measured on silicon (round 4)** | 572,952 B | 4.99 ms (rp0) / 4.50 ms (rp1) | **90.36 ms** | **127.43 ms** | 70.9 % |

The projection landed 1.6 % under the measurement (constant per-load
overhead weighs relatively more on smaller partials).  Read
`docs/LIMITS.md` before trusting these numbers for your design — timing
is NOT modeled, and placement headroom is modeled only as the calibrated
`--headroom` scalar.

## Hardware validation

**Round 1 (2026-07-16): the pre-alignment optimum FAILED placement.**
The 922-frame floorplan (tiles 24..33, both regions) put the site-less
clock-spine column (tile 33) at the pblock edge.  Site ranges cannot
express covering a site-less column, so the emitted pblocks physically
ended at SLICE_X49 — splitting the back-to-back interconnect pair
INT_L_X32/INT_R_X33 against static.  Vivado prohibited placement in both
columns of the split pair (CRITICAL WARNING [Constraints 18-993]/[18-996]
/[18-992]: 100 SLICEL sites excluded per region), rp1 then needed 3,005
LUTs on the 2,800 that survived (107.3 %), and `place_design` failed on
carry-chain shapes ([Place 30-1153]).  The 3,005 vs the 2,972 modeled is
itself a measured fact: +1.1 % netlist growth between the demand snapshot
and the rebuilt design.  Both findings are now in the model: edge
alignment as a hard constraint, and `--headroom` (default 0.93).

**Round 2 (2026-07-16, same day): the fixed model's floorplan failed on
a resource the demand table does not carry.**  The re-solve (the then
default optimum: 4 tile columns x 3 rows per region, 1,050 frames /
424,652 B) rebuilt with ZERO pair-split warnings — the round-1 mechanism
is confirmed fixed — but detail placement failed with [Place 30-487]:
rp1's module needed ~930 SLICES (33 control sets + carry-chain shapes;
one unique control set per slice, so FFs cannot fully pack) against the
pblock's 900, even though its 2,601 LUTs used only 72 % of LUT capacity
and its 1,994 FFs 28 %.  The FLORA-style LUT/FF/BRAM/DSP demand model
has no slice column.

**Round 3 (2026-07-16, same day): the measured `slices` demand — and
the first solved floorplan to SURVIVE the flow.**  The occupied-slice
maxima were measured from all eight routed configuration checkpoints of
the two earlier proven builds (`report_utilization -pblocks`, "Slice"
row): rp0 1,127 / rp1 1,264 — notably ABOVE the ~930 minimum the
failing placer quoted, and driven by the same 33-control-set module in
both regions.  The model now carries slice coverage as a first-class
constraint; this README's tables are from the round-3 solve.  The
round-3 rebuild (same design, same 40 MHz clock, only the floorplan
swapped) went through the ENTIRE flow: all four configurations plus the
blanking config placed with zero placement prohibits and zero
pair-split warnings, routed, and MET timing at the 25 ns clock (WNS
+7.901 / +4.408 / +2.133 / +6.481 ns, TNS 0.000 in all four),
21.2 minutes wall from implementation through the software build.
Predicted vs measured partials:

| partial | predicted | measured (.bin) | delta |
|---|---|---|---|
| rp1 (7 CLB + DSP cols x 2 rows) | 546,660 B | **546,660 B** | **byte-exact** |
| rp0 (5 CLB + DSP cols x 3 rows) | 599,180 B | 599,244 B | +64 B (+0.011 %) |

Both partials' FDRI frame counts parse to EXACTLY the predicted 1,352
and 1,482 frames.  The rp0 delta is packet overhead, not frames: its
three rows span the device's top/bottom half boundary (FAR blocks
top0/row0 + top1/row0 + top1/row1 — 8 FAR writes vs rp1's 6), and each
extra half-crossing FAR block costs 32 bytes the fixed overhead
constant does not carry.  This build also VALIDATED the previously
extrapolated multi-row partial structure (limit 6) and produced the
first silicon-flow artifacts for 2-row and 3-row regions (limit 5's
build gap): rp1's partial is byte-exact against the extrapolated model.
Measured vs the hand floorplan's partials: −30.1 % (rp0) / −41.6 %
(rp1); the average partial drops 896,524 B → 572,952 B.

**Round 4 (2026-07-17): BOARD EXECUTION — the solved floorplan ran on
silicon, bit-exact, and the reconfiguration savings are measured, not
projected.**  The round-3 build (its own 40 MHz first-stage bootloader;
every SD file readback-verified byte-identical after provisioning;
result files pre-poisoned with junk so only a genuinely fresh run could
pass) was executed twice on the Pynq-Z2 over a remote bench, with three
independent readout channels (JTAG DDR mirror, JTAG read of the output
BRAM, SD-card dumps) in byte agreement on both runs:

- **Correctness:** all ten output words oracle-exact both runs
  (argmax 7) — identical to the hand-floorplan build's silicon result.
- **Wall (start bit → design done):** 127,427 / 127,429 µs
  (2 µs run-to-run).
- **Execution excluding reconfiguration: 37,064 / 37,067 µs** — the
  hand-floorplan build measured 37,069 µs on the same instrument:
  **unchanged within 5 µs** (same netlist, same clock; the floorplan
  swap cost zero execution time).
- **Reconfiguration: 90,363 / 90,362 µs over the same 19 loads —
  −35.0 % vs the hand floorplan's 139,119 µs.**  Per-load, measured
  per region (new per-region driver counters, split cross-checks
  exact): rp0 10 loads at 4,987 µs avg, rp1 9 loads at 4,499 µs avg.
- **Byte-scaling check:** at the hand build's measured 122.15 MB/s PCAP
  throughput the predicted per-loads are 4,906 µs (rp0; measured
  +1.7 %) and 4,475 µs (rp1; +0.5 %) — effective rates 120.2 /
  121.5 MB/s.  The flat-throughput model holds; the small shortfall
  is consistent with a constant per-load software/DevCfg overhead
  weighing relatively more on smaller partials.  The projected
  88.9 ms total came in at 90.36 ms measured (+1.6 %).

I keep the full board-run logs (SD image checksums, raw output words,
per-load counter dumps, verification transcript) in my own records —
open an issue if you want them.  Timing remains outside the model
(`docs/LIMITS.md` item 2): round 3 met it, round 4 ran it, but the
model does not predict it.
