# Automatic local memory/compute chains

The current `resource_logic_v1` pipeline enables `joint_chains` in
`resource_partition_config.json`. Legacy physical-score partition experiments
remain frozen. This changes feasible assignments, not the `J = C + L` formula,
resource ratios, cut budgets, or netlist.

## Discovery

`joint_discovery.discover_joint` receives the complete immutable atom/net cache
and existing connectivity-validated arithmetic operators. It does not read routed
locations, manual chain lists, bank numbers, or current module owners.

1. Find the largest nonoverlapping operator ancestor scopes with at most 32,768
   cells. Scopes bound searches; whole scopes are not bound together. Reject
   boundaries crossing physical atoms. Include wrapper registers without assuming
   a fixed hierarchy depth.
2. Propose small exact-parent BRAM/URAM wrappers, including their glue logic,
   with at most 1,024 cells. Reject overlap with an accepted operator or a
   physical atom extending outside the wrapper.
3. Associate a memory with a dominant local compute scope (at least 90% of its
   recognized local operand-input sink pins). Other readback traffic is reported
   and retained outside the unit; this does not assert that memory is private.
   Shared multi-bank muxes are combining boundaries, not transparent links.
   Memories serving independent operator components in one scope are excluded.
4. Follow weight-4 directed nets to the first complete operator/memory stage.
   Existing FFs and simple LUT/buffer bridges are transparent; combining LUTs,
   unaccepted arithmetic, other hard memories and scope exits stop traversal.
   FF enable/reset connections can be classified weight-4 by the existing cache,
   so an FF is not rejected merely for multiple incoming nets. Both ends of a
   corridor require at least eight distinct qualifying bit-nets; one-bit
   broadcast cannot meet this width gate. This is a structural heuristic on the
   existing cell-level graph, not pin-arc semantic proof.
5. Bound a corridor to eight intermediate hops and a chain to 4,096 bridge atoms;
   ignore nets with more than 64 sink pins. Keep actual connecting atoms, complete
   stages and evidence. Reject shared corridors and chains exceeding the unchanged
   anonymous single-die resource budget.

These are conservative engineering defaults, not calibrated timing guarantees.
Rejected/unsupported chains remain ordinary atoms plus protected operators.
Narrow chains, flattened hierarchies, long pipelines and shared memories may need
later policies. Global control and whole hierarchy subtrees are not absorbed.

## Protection through the current flow

- Replace covered operators with complete joint chains, retaining other accepted
  operators. Contract this disjoint set before native KaHyPar; its coarse search
  and refinement see each chain as one vertex.
- Expand to original atoms and check integrity. Whole-module merges preserve
  these units, with another check after merging.
- Pass the same protected set to local operator/component refinement. Reject
  already-broken inputs; partial moves cannot split an intact protected unit.
  Check after refinement and subsequent merges.
- Retain broken historical candidates as controls, but exclude them from refinement
  admission and final ranking. Ranking recounts integrity from actual groups,
  not cached pass flags, even if a broken candidate has a lower J.
- Bind units to graph/configurations through `protection_manifest.json`. Enabled
  runs with missing or changed protection data fail closed.
- Check before delivery and floorplan preparation. Export `joint_chains.json` and
  `joint_chain_cells.tsv.gz`; ordinary floorplan export and implementation-input
  packaging carry these identities forward.

`operators.pkl` still means individual operators. `protection_units.pkl` is the
compound/operator set; `joint_chains.pkl` contains joint chains only. Original
C/L, membership and all resource totals remain authoritative. `batch_move`
remains available for explicit repairs.

No primitive, net or FF is created, removed or reconnected. Traversing FFs does
not imply a single-cycle timing path. Same-module does not guarantee physical
same-die placement if a region spans dies or a soft pblock spills; use exported
identities in downstream physical audits.

Focused checks:

```sh
python3 -B -m unittest test_joint_discovery test_joint_units test_structure_frontend test_resource_partition
```

GETRF's 2026-09-25 regression automatically finds 256 chains of 1,833 cells each.
The previous eight manual repairs are an independent comparison, not discovery
inputs. Standard source retains seeds 0/1 and initial targets 1/2 CR; complete-cache
integration validation uses seed 0 / 2 CR to bound test time.
