# originalpart: connectivity partition baseline

Saved at the user's request on 2026-09-18, before the proposed three-step
partition improvements. The publication branch is `originalpart` in
`Lvjylean/non_dataflow_case`. Existing Python/Tcl algorithms are preserved.

## Scope

This source-only snapshot includes this standalone directory: native
leaf/connectivity extraction, graph construction, KaHyPar invocation, merging,
result generation, tests and the exact `km1.ini` used by the completed run.

The source checkpoint, raw graph, graph cache and completed netlist-derived
artifacts remain in the existing local/server experiment records. Leaf
membership, resource/connection tables, generated reports, DCPs, EDIFs and
dependency binaries are not part of this publication. Independent, ongoing
floorplan work is outside this partition snapshot.

## Baseline settings

- KaHyPar 1.3.7, km1, initial k=8, cell cap=150000, seeds 0 and 1.
- Whole-device resource caps; no equal-size or minimum-size requirement.
- Original hierarchy is provenance; dedicated cascades/MUX structures are atoms.
- Connected blocks merge in descending km1 gain while capacities permit.

The historical run initially used a single-SLR resource cap and then reapplied
the corrected multi-SLR merge policy to both frozen candidates. The current
source uses the corrected policy from the start. Existing experiment artifacts
remain the historical baseline; a fresh run is not claimed to reproduce every
intermediate candidate byte-for-byte. Full provenance and frozen candidates
remain in the original server run.

The bundled configuration was copied unchanged from that run's
`source/km1.ini`; it uses the KaHyPar km1 preset settings. KaHyPar itself remains
an external dependency: <https://github.com/kahypar/kahypar>.

## Validation and execution

From the repository root, run the four focused tests:

```sh
python3 -m unittest discover -s FPGA_benchmark/netlist_hier_floorplan/connection_partition -p test_partition.py -v
```

For a new server experiment, copy this directory to the new run's `source`
directory so `source/km1.ini` is available. Follow the extraction and execution
sequence in [README.md](README.md). Reuse only raw files and caches bound to the
same immutable checkpoint. The existing `report.py` contains case-specific
interpretation for this five-module result; update that interpretation before
using it to describe a different partition.

`baseline_manifest.json` records source hashes and the focused test result.
No full partition or Vivado rerun is needed merely to archive this source.

## Gate for the next published version

The user explicitly requires validation of effectiveness before the next
version is committed and uploaded. The proposed sequence is:

1. Replace unconditional capacity-safe merging with selective merging.
2. Add soft logical-core preferences and boundary-cell adjustment.
3. Add static heterogeneous-resource/region feasibility evaluation and local
   splitting, especially for P01.

Develop candidates separately from this saved baseline. Before publishing a
next version, compare against the existing baseline artifacts using the same post-opt input
and real-net accounting, check complete unique ownership/resource conservation,
and document observed benefits and tradeoffs in connectivity, logical cohesion,
physical planning flexibility and module count. Lower km1 alone across different
module counts is insufficient evidence. Do not claim timing or SLL improvement
without physical evidence. Unvalidated changes must not be promoted to a new
published partition version.
