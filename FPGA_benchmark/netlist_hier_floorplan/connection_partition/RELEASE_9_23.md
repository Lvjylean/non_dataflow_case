# Partition and floorplan source — 2026-09-23

Branch: `fast_partition_floorplan_9.23`, based on
`codex/partition-floorplan-9_22` (`5f79c3e86edebfc606c0f6884772e53b0f2339d0`).
This branch publishes reusable source, configuration, tests and documentation.
It does not contain extracted netlists, module memberships, DCPs, device
inventories, routed results or experiment caches.

## Changes from 9/22

- `balanced_generate.py` can run independent KaHyPar local-split proposals in
  `--workers N` forked processes. The graph is loaded once before forking;
  each worker writes only its own tagged KaHyPar input, while the parent
  serializes candidate summaries in deterministic seed/parent order.
  `--workers 1` retains serial execution. Existing completed candidates can
  be reused when resuming an interrupted generation.
- A new design can omit the historical three-step `previous` candidate.
  Indivisible small parents remain intact. Resource-driven proposals use enough
  blocks for the resource demand instead of assuming two blocks always suffice.
- `partition.py deliver` reads `RUN/input_binding.json` for the input DCP
  identity and hash. The historical TRTRS fallback is kept for old runs.
- The directed fixed-membership search and cache-only floorplan entry accept
  sequential `S00`, `S01`, ... module IDs of any count. Historical filenames
  such as `fixed11_search.py` remain for compatibility. Fresh-run cache
  bindings and the older immutable-file bindings are both checked.
- Guards for one-module search proposals and a longer plot palette permit the
  same floorplan algorithm to run on the 12-module GETRF case.

## Running the source

Prepare a trusted post-opt connectivity export, graph, device CR inventory and
baseline candidate as described in `README.md` and `RELEASE_9_22.md`. For a
new design, write `RUN/input_binding.json` with `input_dcp` and
`input_sha256` before `partition.py deliver`. Both values must identify the
actual optimized checkpoint used to build the graph.

```sh
python3 RUN/source/balanced_generate.py RUN --workers 3
# Or include PREVIOUS after RUN to retain the historical previous6 candidate.
python3 RUN/source/balanced_generate.py RUN PREVIOUS --workers 3
python3 RUN/source/floorplan_cached.py NEW_OUTPUT --from-run TRUSTED_CACHE_RUN
```

Use `--workers 1` when independent KaHyPar jobs must run serially. The
parallel option changes scheduling, not the partition objective, resource
limits or floorplan cost. It uses process `fork`, so it is intended for the
Linux server environment. The cache-only floorplan still requires a bound
input and performs its own resource, objective and soft-region checks. Module
memberships remain fixed during that floorplan search.

The 2026-09-23 GETRF planning run used three workers to finish independent
candidate generation and validated its 12-module partition and floorplan.
It switched scheduling after a partial serial run, so it is **not** a
controlled serial-versus-parallel timing benchmark. This release makes the
working scheduling option reusable; it makes no measured end-to-end speedup
claim and does not include a new physical implementation result.

## Validation

```sh
python3 -m unittest discover -s \
  FPGA_benchmark/netlist_hier_floorplan/connection_partition -p 'test_*.py' -v
```

The focused parallel tests compare serial and forked proposal results, verify
reuse of completed candidates and check resource-driven block count and
indivisible-parent handling. The 9/22 release manifest is retained as a
historical source snapshot; the 9/23 publication receipt records the new
commit and test result.
