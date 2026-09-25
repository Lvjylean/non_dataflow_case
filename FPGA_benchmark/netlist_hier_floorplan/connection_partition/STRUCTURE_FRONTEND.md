# Optional reversible operator frontend

This entry leaves the existing partition and floorplan defaults unchanged.
It uses an immutable post-opt graph and preserves the previous selected
partition as a control. It runs no Vivado, placement, routing or netlist edits.

`structure_frontend.py` proposes disjoint arithmetic operator subtrees from
configurable instance-family patterns. Naming alone is insufficient: each
proposal is checked against physical-atom boundaries, size, weighted internal
driver-to-sink connectivity and largest internal component. Unrecognized or
rejected logic stays as the original physical atoms. Physical atoms are never
split. Accepted operators are contracted only for KaHyPar; cell weights and
every resource dimension are summed. Parallel quotient edges are combined.
Coarse self edges can be omitted for cut/km1 only. The original graph and
directed sink multiplicities remain mandatory for all final scoring.

`structure_refine.py` expands to the original atom graph, then tries complete
operator repairs and whole connected-component moves from loosely connected
modules. Already complete accepted operators cannot be split in the same local
round. A move must not increase real km1, weighted directed pin cuts or operator
minority cells, and must improve at least one. Device-wide resource totals are
screened; the existing joint CR-region evaluator remains the physical feasibility
gate. The search budget excludes graph-index construction and final validation.
The component threshold schedules candidates; it is not an objective rewarding
100% connectivity. No equal-size objective is introduced.

`structure_pipeline.py` initially adapts the trusted GETRF cache-run layout:
`graph.pkl`, `cr.tsv`, `planning_source/`, `baseline/`, and `balanced/` with
complete original candidates, cores and input bindings. Other designs can use
the two pure-Python libraries directly or supply the same validated cache layout.
An unverified arbitrary pickle is not a supported input. In the first version,
the previous coarse bootstrap and a two-way split family each use two seeds;
their best cut candidates and the repaired current partition are sent to at most
five new static region evaluations. Both the operator-only repair and the split
candidate before component merging remain eligible as stage fallbacks: lower
km1 alone must not force oversized modules into the final result. The old selected
partition remains eligible.
No global optimality or timing improvement is claimed by this candidate policy.

```sh
python3 structure_pipeline.py run NEW_RUN \
  --from-run TRUSTED_COMPLETED_GETRF_RUN \
  --kahypar-python /usr/bin/python3 \
  --kahypar-path EXISTING_KAHYPAR_BINDING_DIRECTORY
```

The controller runtime needs the already used NumPy/Gurobi/matplotlib environment.
KaHyPar generation can use the separate existing Python binding. No dependencies
are downloaded. The source snapshot freezes the original comparison configuration;
the final directed floorplan keeps internal communication weight beta=1.

Outputs include operator acceptance/rejection evidence, quotient mapping,
per-stage times, exact cut invariance checks, local-move history, expanded module
resources/connections, bounded candidate comparison, and independently checked
core/soft floorplan inputs. Large netlist-derived artifacts remain server-side.

```sh
python3 -B -m unittest discover -s . -p test_structure_frontend.py -v
```
