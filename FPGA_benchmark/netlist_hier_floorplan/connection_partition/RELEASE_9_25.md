# Partition and floorplan source — 2026-09-25

Requested branch: `partition-floorplan-9_25_删除D/WK/保护子算子`.
Base: `fast_partition_floorplan_9.23`, commit
`53aa7bf01dce2f988a1f2009c6a0ff883b20d187`.
This snapshot contains reusable source, configurations, tests and documentation.
Design checkpoints, extracted connectivity, memberships and experiment caches
remain outside the publication.

## Active partition

- `structure_pipeline.py partition` selects `resource_logic_v1`: `J = C + L`.
  D, `0.0025 W k`, and the fewer-modules tie preference are absent from active
  scoring. Historical physical-score entry points remain for reproducibility;
  their presence does not enable D in this mode.
- Check every resource against one common anonymous die capacity vector:
  non-URAM 70%, URAM 100%. The 1-CR equivalent lower bound is soft; weakly
  connected small modules can remain. Initial 1/2-CR targets and seeds 0/1 are
  candidate-generation settings, not equal-size or fixed-module-count targets.
- Connectivity-validated complete operators are contracted before KaHyPar.
  Automatic discovery now also joins local memory/compute stages and existing
  FF/LUT bridges into disjoint protected chains, subject to resource bounds.
- Preserve these units through expansion, merging, local refinement, candidate
  admission, exact ranking, export and floorplan preparation. Broken historical
  assignments remain controls and cannot win the current protected search.
- Export chain identities and bind protection metadata to graph/configuration
  hashes. Discovery does not consume manual chain lists or routed locations.

See [RESOURCE_PARTITION.md](RESOURCE_PARTITION.md),
[STRUCTURE_FRONTEND.md](STRUCTURE_FRONTEND.md), and [JOINT_UNITS.md](JOINT_UNITS.md).

## Floorplan

Physical cost remains in the separate floorplan stage. The current
`boundary_spatial_v1` hypernet model uses hard-resource associations and module
boundaries; traversing existing FFs describes spatial association, not a
single-cycle STA path. The directed cost and multi-SLR branch penalty remain.

Keep non-URAM resource limits at 70%, URAM at 100%, SLR distance weight 8,
directed weight 1, branch-square coefficient 32 and soft extension threshold 50%.
Core regions determine resource accounting and J. Extensions add geometry only;
modules may share qualifying CRs that were empty in the core solution.
Inherited parent regions are supported as explicit optional candidates.
Routed resource-density fitting is disabled. The newly discussed congestion
pressure model and internal chain-group region planning are not implemented here.

## Entry points and dependencies

Use Python 3 with NumPy and the existing native KaHyPar installation. Subsequent
floorplan initialization also requires the existing Gurobi environment, and
plotting requires Matplotlib. Native Vivado extraction and implementation remain
separate operations. No dependency or third-party source is changed by this
publication. Prepare a trusted post-opt cache as described in
[RESOURCE_PARTITION.md](RESOURCE_PARTITION.md).

```sh
python3 structure_pipeline.py partition /absolute/new_run \
  --from-run /absolute/trusted_cache_run \
  --kahypar-python /absolute/kahypar_python \
  --kahypar-path /absolute/kahypar_module_dir
python3 structure_pipeline.py floorplan /absolute/new_run
```

The source package also includes the required sibling
`balanced_implementation/adapter.tcl`. Historical release manifests describe
their original snapshots; `release_9_25_manifest.json` describes this one.

## Validation and limitations

All 134 local unit/integration checks passed before publication. The standalone
source package has an optional local U250-inventory fixture test; it is explicitly
skipped when that non-published inventory is absent. Package validation is
recorded in the release manifest and publication receipt.

The completed GETRF native regression used seed 0 and initial target 2 CR,
without changing public defaults. It found 256 chains, preserved all 1,026
accepted operators, and selected 10 modules. Complete-chain splits fell from
39 in the historical 9-module control to zero; C changed from 5918 to 4668.75,
L from 137 to 85, and J from 6055 to 4753.75. The earlier count of eight split
chains used only DSP/URAM endpoints, not full-chain membership.

Membership and resources were independently checked on the original graph.
These are partition results, not proof of lower congestion or better timing.
No new full floorplan, placement or routing was run for these 10 modules.
Same-module membership does not force physical same-die placement if a region
spans dies or its soft constraint spills. No primitive, net or pipeline stage
is created or rewired by joint-chain protection.
