# Connectivity-only coarse modules

The local optional [chain-region guidance](CHAIN_GUIDANCE.md) stage can subdivide
large floorplan parents into intact-chain physical groups without changing the
logical partition. Enable `--chain-guidance` for a new parent floorplan, or use
`chain_guidance.py` to reuse a validated parent result. This local extension is
separate from the published 9/25 snapshot below.

The 2026-09-25 source snapshot uses **resource-constrained partition (C+L)**
followed by independent floorplanning. It removes D and the module-count penalty
from the active partition objective and enables automatic local memory/compute
chain discovery and protection throughout that flow. See
[RELEASE_9_25.md](RELEASE_9_25.md),
[RESOURCE_PARTITION.md](RESOURCE_PARTITION.md) and
[JOINT_UNITS.md](JOINT_UNITS.md) for the active `structure_pipeline.py partition`
entry point, resource bounds and validation limits. The complete GETRF regression
selected 10 modules with all 256 discovered chains intact; this version has not
been physically validated by a new floorplan or placement/routing run.

[RELEASE_9_23.md](RELEASE_9_23.md) records the preceding release, including the
optional parallel partition proposal generator and fixed-membership floorplan.
[RELEASE_9_22.md](RELEASE_9_22.md) records the previous release.
The baseline description below remains historical. The balanced partition
objective and the subsequent fixed-membership floorplan have separate configs.

The pre-improvement `originalpart` source version and gate for the next
publication are documented in [BASELINE.md](BASELINE.md).

This entry point implements the 2026-09-18 request for coarse modules from the
immutable TRTRS post-opt checkpoint. It does not query timing paths, routed
locations, or physical feedback and does not run placement or routing.

`connectivity.tcl` exports complete native connectivity using the outermost
primitive inventory in `cells.tsv`. It includes top-direct leaf cells and every
original child hierarchy. Native protected-IP cells remain visible; the EDIF
export attempted during the first run is not an input to partitioning.

`partition.py` builds an undirected cell hypergraph while retaining driver/sink
direction for the final module connection tables. Constants and clock
infrastructure retain ownership but are excluded from clustering. Ordinary or
mixed nets weigh 1; nets whose cell sinks are all recognized control pins weigh
0.25. Top ports are retained separately and have no placement vertex. Dedicated
DSP/RAM/carry cascades and LUT/MUXF7/MUXF8 structures are contracted as atoms.
An ordinary high-fanout data net is not discarded or expanded into a clique.

Initial execution uses KaHyPar 1.3.7 with its km1 direct-kway configuration,
seeds 0 and 1, k=8, and individual upper bounds of 150,000 primitive cells.
There is no equal-size or minimum-size objective. Logical modules may span SLRs.
The final hard resource bound is the whole four-SLR device, not one SLR. Per-SLR
raw capacities (LUT=432000, FF=864000, DSP=3072, BRAM18=1344, URAM=320) are used
only to report a resource lower bound on the number of SLRs. Connected blocks
are merged, in km1-reduction order, while the cell cap and whole-device resource
caps remain satisfied. The final module count may differ from 8. Select
the candidate with minimum final weighted km1, then weighted cut.

The first run initially tried single-SLR resource caps and produced a local URAM
split. This was corrected during the run to respect the user's multi-SLR module
requirement. Frozen candidates are retained; final delivery reapplies the same
multi-SLR merge policy to every candidate. The corrected policy must not be
described as enforcing single-SLR modules or geometric feasibility.

The original hierarchy is retained as provenance and summarized by module;
it does not prevent top-direct cells from joining cells from other hierarchies.

## Outputs

- `leaf_cells.tsv.gz`: all independent primitives, original hierarchy, resource
  demand and new module membership; CONSTANT/CLOCK/FREE are explicit categories.
- `module_resources.tsv`: resource demand, top-direct membership and communication
  totals. LUT is a conservative primitive count, not packed physical LUT usage;
  LUTMEM is a subset of LUT. BRAM18 counts 18K-equivalent units.
- `module_connections.tsv`: directed module pair, unique bit-net count, number of
  sink-pin connections, weighted net count, and data/control counts. A net reaching
  several modules contributes to each destination pair, so the matrix sum differs
  from the unique cut-net count. Pins on the same sink cell are distinct connections.
- `port_connections.tsv`: top-level I/O separately from module-to-module edges.
- `module_hierarchy.tsv`: original-owner composition, including TOP leaf cells.
- `modules.json`: compact machine-readable module set, settings and totals.

Every leaf cell receives exactly one label. Primitive resource totals and original
hypernet cut/km1 are checked during generation; no separate coverage, timing or
physical-feedback report is produced. A module with no module-to-module connection
is marked ineligible for floorplan constraints. No netlist rewrite is performed.

## Execution

The current main floorplanner adds a register-bounded exponential SLR term.
See [CUMULATIVE_PATH_FLOORPLAN.md](CUMULATIVE_PATH_FLOORPLAN.md) for the formula,
single-SLR core policy, incremental propagation, coverage and cache migration.

The optional post-floorplan control repair is documented in
[CONTROL_PATH_REFINEMENT.md](CONTROL_PATH_REFINEMENT.md). It consumes a frozen
post-opt graph plus validated routed paths and exports a separate input; it does
not change the default standalone partition objective.

Run all native Vivado operations and full-netlist work on eda070 in a fresh run
directory. `partition.py prepare RUN` creates a cached graph;
`partition.py partition RUN --k 8 --cell-cap 150000 --seed SEED` creates a candidate;
`partition.py deliver RUN` writes the selected result. Use the already installed
KaHyPar environment and place its km1 configuration at `RUN/source/km1.ini`.

`test_partition.py` checks independent expected hypernet and sink-pin counts,
control weights, port separation, resources and dedicated-connection semantics.


### Resource-specific URAM soft envelopes

`uram_soft_export.py` exports a new input directory from a verified core/soft input. It requires the requested module's core URAM demand to equal its core capacity, and permits vertical envelopes only. Core geometry, resource accounting, objective and membership are preserved byte-for-byte where applicable. Only URAM288 site ranges are appended to each existing soft Pblock. This is additional placement guidance, not capacity credit or a utilization prediction.

Supply `--previous`, `--output` (new directory), `--device` (`cr.tsv`) and `--requests` (JSON mapping module IDs to `[x0,y0,x1,y1]`). The generated `regions.tcl` loads its bundled `uram_resource_adapter.tcl`. Backend audits must honor `bi_expected_sites` and `bi_cell_inside_soft`; the common `backend_generic/audit.tcl` supports these optional hooks. `bi_load` clears prior resource additions when changing inputs. Historical backends that compare only whole-CR site sets need the compatible audit patch.

Validated GETRF input and compact native evidence: [S02/S14 URAM extension](../../reports/getrf_uram_soft_20260926_01/README.md). No placement or route is invoked by this exporter.
# Optional directed local-unit refinement (2026-09-27)

Use `structure_pipeline.py partition ... --directed-units --macro-timing ...`
to add name-independent register-bounded cones and joint moves while retaining
KaHyPar, the experiment's resource/affinity settings and exact C+L selection.
See [DIRECTED_UNITS.md](DIRECTED_UNITS.md) for the isolated cache-validation
entry point, coverage boundaries and output semantics. This is not a new
floorplan or a routed-timing certificate.
