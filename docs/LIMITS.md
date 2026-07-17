# Where the model is cruder than reality (honest limits)

This list is carried over, nearly verbatim, from my validation notes for
the prototype this package was extracted from.  "The case study" below is
the two-region Pynq-Z2 design in `examples/lenet_pynq/`; "the validated
flow" is the Vivado 2019.1 DFX flow that produced its measured partials.

1. **Placement/routing headroom is modeled only as a calibrated scalar.**
   The first hardware build of a solved floorplan (2026-07-16) supplied a
   measured calibration point: the netlist grew between the demand
   snapshot and the rebuilt design (rp1: 3,005 LUTs assigned vs the 2,972
   modeled from the previous build's post-route reports, +1.1 %), and the
   placer failed outright at 107.3 % post-exclusion demand (carry-chain
   shapes would not commit), so the honest packing ceiling sits below
   93 %.  The `--headroom` knob (default 0.93, multiplied with
   `--derate`) prices that in; `--derate` remains the user's own
   design-margin knob on top (0.5 shown in the example; the hand
   floorplan ran at 45 %/32 %).  What the scalar does NOT capture:
   routing of wide memory boundary bundles into narrow regions, and the
   true placeable threshold for a given module structure — 107.3 % is
   measured-fatal, but the highest packing proven to place on this flow
   is still the hand floorplan's 45 %.

   **Measured sequel (round 2, same day): LUT/FF demand alone
   under-models SLICE packing — control sets bind before LUTs.**  The
   re-solved floorplan (both x-edges pair-aligned; zero pair-split
   warnings — the round-1 mechanism is confirmed fixed) failed detail
   placement anyway, on a resource the FLORA-style demand table does not
   carry: slices.  Vivado [Place 30-487]: the region held 2,601 LUTs
   (72 % of its 3,600-LUT capacity, comfortably inside the headroom) and
   1,994 FFs (28 %), but its 33 control sets and carry-chain shapes
   needed ~930 slices against the pblock's 900 (511 committed + 419
   still required vs 389 free; a slice holds only one unique control
   set, so FFs cannot fully pack).  **Fix (round 3, same day): the
   demands now carry a `slices` column**, covered by CLB cells at
   `per_cell["slices"]` each with the same derate × headroom margin.
   The case-study demands were re-measured as occupied-slice maxima
   from the proven builds' routed checkpoints
   (`report_utilization -pblocks`, "Slice" row, max over the four
   configurations: rp0 1,127 / rp1 1,264 — note the as-routed occupancy
   is well ABOVE the ~930 minimum the failing placer reported, and the
   worst module runs 2.35 LUTs/slice as routed, not 4).  Residual
   limits: control sets themselves are still not modeled (the slice
   demand is their measured proxy — a future module with even fewer
   FFs per control set could shift the ratio), and when the `slices`
   column is absent the ceil(lut/4) perfect-packing default is
   OPTIMISTIC by exactly the mechanism this failure measured — prefer
   measured occupancy from a routed design.  **Measured closure (round
   3, same day): the slice-demand rebuild PASSED the whole flow** —
   all four configurations plus the blanking config placed with zero
   prohibits, routed, and met timing at the target clock; see the case
   study's "Hardware validation" for the predicted-vs-measured partial
   sizes (rp1 byte-exact; rp0 +64 B of measured FAR overhead, item 6).

2. **Timing is not modeled at all.**  A hand-fencing probe on the case
   study measured that pblock fencing moves timing mass around without a
   net total-negative-slack win on the hand geometry, but that witness
   does not cover the geometries this tool produces (vertical stacking,
   regions adjacent to the clock spine).  The case study had >= 3.6 ns of
   slack at its 40 MHz clock in all four configurations; the risk on other
   designs is nonzero and unquantified.

3. **The static region's non-BRAM appetite is only a reservation.**  In
   the case study, static LUT/FF (5,232/5,862), the processor subsystem's
   fixed corner, the AXI bridge and the 12 BRAM controllers are not
   spatially modeled; the MILP only guarantees the reserved BRAM stays
   outside the regions (`--static-bram`).  Static router congestion around
   stacked reconfigurable holes is unmodeled.

4. **Special (site-less) columns: the edge case graduated from limit to
   constraint; the interior case is half-validated.**  A special column
   at a region EDGE is unrealizable: pblocks are materialized as site
   ranges, a site-less column contributes none, so the physical pblock
   edge retracts into the neighboring site-bearing column — mid-pair —
   and Vivado prohibits placement in BOTH columns of the split
   interconnect pair.  This was MEASURED on the first hardware build
   (2026-07-16, CRITICAL WARNING [Constraints 18-993]/[18-996]/[18-992]:
   100 SLICEL sites confiscated per region, placement failed); the model
   now forces specials interior, which together with the pair rule pins
   both emitted x-edges to pair boundaries.  A special column INTERIOR
   to a region: the one the hand floorplan spanned (x=50 on xc7z020) is
   silicon-validated, and its 30-frame cost is measured; the other
   (x=33) has never been inside a built region, its cost assumed by
   class.  UG909 explicitly contemplates pblocks spanning the center
   clock column.  The `--forbid-specials` knob still bounds the
   downside; on the case study it now costs nothing (the current
   optimum uses no special columns).

5. **Vertical stacking and upper-row rectangles: flow-proven in round 3,
   board-proven in round 4.**  Every silicon pblock behind the original
   measured data sat in clock-region row 0, side by side.  The round-3
   rebuild (2026-07-16) put a 2-row region (rows 0–1) and a full-height
   3-row region through the entire flow — placed, routed, timing met,
   partials written — and the round-4 board run (2026-07-17) executed
   that build on the Pynq-Z2 with bit-exact outputs and measured
   reconfiguration times.  Residual gap: both regions include row 0; a
   rectangle covering only upper rows has never been built.

6. **Multi-row partial structure: measured for 2 and 3 rows; one
   32-byte-per-block FAR overhead is documented, not modeled.**  The
   model assumes one FDRI block per covered clock-region row (+1 pad
   frame each) with the same doubled write and the same fixed preamble.
   The round-3 rebuild's parsed partials confirm the frame accounting
   EXACTLY for a 2-row and a 3-row region (1,352.00 and 1,482.00
   frames); the 2-row partial is byte-exact.  What the fixed
   452-byte overhead constant does not carry: a region whose rows span
   the device's top/bottom half boundary needs extra FAR-write packet
   blocks (the 3-row partial: 8 FAR writes vs 6, +64 bytes = 32 bytes
   per extra half-crossing block, +0.011 % of the file).  The preamble
   and overhead constants are otherwise flow-invariant across all
   parsed partials, but all were produced by one Vivado version
   (2019.1) with RESET_AFTER_RECONFIG; other versions/settings may
   differ.

7. **Demands are post-synthesis maxima from a finished build.**  A
   floorplan-before-implementation flow would consume predicted resource
   demands instead; prediction error becomes headroom error (see limit 1).

8. **The DSP/BRAM frame split rests on one bounding-box reading.**  The
   28/28 frames-per-column split for DSP and BRAM columns is pinned by
   four measured equations only under a specific reading of one recorded
   floorplan's bounding box; the parse-level proof was not possible
   because those bitstream files had been cleaned from disk.  A +-2 frame
   error in the split would move size predictions by < 0.5 %.

9. **Frame constants are 7-series numbers, measured on xc7z020.**  The
   geometry side of a device model is fully probe-derived, but the frame
   table (36/28/28/30, 128 content frames, 404 bytes/frame, preamble and
   overhead) must be re-measured before the `frames` objective is trusted
   on another device family — see `tools/build_device_model.py`.
