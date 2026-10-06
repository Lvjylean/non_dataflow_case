# Optional control-cone and cumulative-path refinement

This stage refines a validated physical-group input. It does not change the
standalone partition objective `C+L`, rewrite the netlist, add pipeline stages,
or fit routed resource density. Existing memory/DSP region geometry and all
protected data-chain members remain fixed. Only bounded control attachments
can change membership; small logic-only modules may translate their existing
single-SLR core rectangle if that improves the new objective.

Run on the experiment server with a fresh output directory:

```sh
python control_path_refine.py PARTITION_RUN GUIDED_IMPLEMENTATION_INPUT \
    ROUTED_WORST_PATH_REPORT NEW_OUTPUT
```

`PARTITION_RUN` supplies the original post-opt graph, resource table, protection
bundle and frozen partition/floorplan configurations. The existing routed setup
report supplies criticality and precisely mapped control-path evidence. Exact
original names and every original directed edge must validate; no guessed
replica alias is accepted. Only known `f96_identity_<number>` helpers may be
projected out, and only if the resulting original edge exists. Excluded traces
remain in `feedback.json`. A missing or wholly unmappable report fails closed.

## Cost

For a path p with successive cell SLRs s_i, use

```
N(p) = sum_i abs(s_(i+1) - s_i)
Nmax(t) = max_{supported same-cycle paths ending at t} N(p)
P = sum_t criticality(t) * max(0, Nmax(t) - 1)^2
J_control = cut_weight*C + logical_core_weight*L + D_directed + 128*P
```

`D_directed` retains the established directed-net and branch-square terms
(current distance weight 8, branch-square weight 32). The new path term counts
every adjacent SLR boundary along a path, including repeated boundaries; it is
not the endpoint distance. Endpoint maxima avoid multiplying penalties merely
because a timing report lists duplicate or reconvergent paths. Criticality is
`1 + 15*clip(1-slack_ns/2, 0, 1)`, taking the maximum observed criticality for each
endpoint; unobserved endpoints have weight 1. No cost normalization is applied.
This is the optional local-refinement objective, not a replacement or a numeric
continuation of historical full floorplan J with D_hyper.

FDRE/FDSE -> LUT/CARRY8/MUXF7/MUXF8 -> FDRE/FDSE structural paths are evaluated
by maximum-distance DAG propagation, stopping at every register. RAM/DSP and
other opaque macros are supplemented only by validated reported traces; their
internal register modes are not invented. The graph is a conservative cell-level
connectivity proxy, not STA sensitization. Single-SLR core regions are required.
Soft-Pblock spill and actual routed detours still require implementation checks.

## Moves and guards

* HLS control names identify candidate evidence, not automatic hard hierarchy
  groups. A local launch/done attachment may follow its unique protected-chain
  owner; bounded destination combinational cones may follow their capture owner.
* Shared cone atoms with competing capture owners stay fixed. Complete original
  physical atoms move together; protected chain/operator atoms never move.
* Units contain at most 128 cells by default. A move must strictly reduce the
  objective, retain nonempty modules, satisfy anonymous die budgets, and satisfy
  per-core and overlapping per-CR resource limits. Logical C may rise at most 5%.
* Control repair, small-region search and a second repair pass run in order.
  This is finite greedy refinement, without a global optimality claim.
* Soft extensions use the existing edge50 rule and add no capacity. Unchanged
  cores retain their original soft envelopes.

Outputs include the complete new `implementation_input/`, corrected logical
and physical exports, changed-cell list, accepted/rejected candidate trials,
coverage and before/after costs, and resource/floorplan figures. Use the new
membership and regions together. `complete.json` binds generated outputs;
source/input hashes, independent scalar path and directed-cost checks, resource
conservation and protection checks accompany each run.

Tests: `python -m unittest test_control_paths -v`. These cover cumulative
roundtrips, register stops, reconvergence, opaque macros, strict trace binding,
shared controls, protected units, reversible atomic moves and resource/C guards.
