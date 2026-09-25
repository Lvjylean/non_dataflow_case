# RAM-triggered soft-Pblock export

The current replacement rule is documented in [EDGE_PADDING.md](EDGE_PADDING.md):
`edge_padding_export.py RUN CORE_RUN_OR_IMPLEMENTATION_INPUT` adds initially empty,
same-SLR CRs beside module edges whose aggregate resource utilization exceeds
50%. Apply it once to the original J-selected core, before any soft padding.
Every eligible module may add the same core-empty CR; overlapping soft ranges
are allowed. Do not reserve a newly added CR for only one module.
Do not combine it with a S01 whole-SLR override or the old RAM80% rule.
The historical RAM-right implementation below remains only for reproduction.

`soft_padding.py RUN PREVIOUS_DIRECTED_RUN` derives a new implementation input
without changing the eleven-module partition or rerunning the region solver.
Run on eda070 with the frozen dependencies and `prepare_adapter.py` snapshot.

URAM and BRAM18 are evaluated separately against the **core region capacity**.
If either exceeds 80% (strict >; no rounding), extend only the right X boundary
by one clock-region column. Clip at the device edge and record the reason when
no expansion is possible. Whole-module CLOCKREGION ranges expand; other modules
are not enlarged indirectly. A padded input is rejected to prevent accumulation.
The threshold does not lower or otherwise modify the core capacity limits.

- `core_solution.json`: immutable original optimization result and objective.
- `solution.json` / `export/static_regions.json`: final soft envelope, with
  diagnostic cost recomputation explicitly distinguished from optimization.
- `padding.json`: original ratios, triggers, bounds and exact added CRs.
- `implementation_input/regions.tcl`: the expanded bounds actually consumed by
  the existing `bi_apply` adapter, which uses IS_SOFT=true.

`padding_verify.py` independently checks the requested transformation, all
resource overlaps, immutable members/input hashes, Tcl loading and objective
arithmetic. `padding_report.py` produces the standard seven-section report and
LUT/URAM/DSP estimate plots. Neither generation nor verification runs Vivado.
