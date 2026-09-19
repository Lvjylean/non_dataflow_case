# Strict ordinary-network fanout experiment

Queries expand the hierarchical net segments once, then select `IS_LEAF` pins.
Exact tree traversal batches NAME values and visits complete levels; repeated
indexing or slicing of a native PIN container is avoided. They also avoid
recursively expanding every segment again with `get_pins -leaf`; the
latter was extremely slow on global clocks. Native PIN and PORT collections are
kept separate, including for top-level input drivers.

Target: logical and physical fanout at most 96, providing margin below the user's
strict 100 limit. This is a post-placement netlist ECO flow for Vivado 2023.2.
The entry point accepts an existing routed DCP and a new output directory.
It preserves placement hints but unroutes before editing and physical optimization;
Vivado skips phys_opt_design on a partially routed checkpoint, so the prior routes
must not be mistaken for a valid post-placement optimization state.
It retains original P00-P04 membership, original Pblocks, timing constraints and
all existing functional registers. The independent partition-improvement result
is not an input to this experiment.

## Changes relative to the 260/512 experiment

* Discover from all live hierarchical nets, including later-generation register
  replicas and their upstream D/CE/control drivers. No seed-list coverage claim.
* Flatten only the owned `hfg_identity_*` LUT1/INIT=2'h2 trees and prove their
  exact original leaf sink sets before rebuilding them. Preserve other logic.
* Construct identity distribution trees, first grouping actual load locations
  by SLR/CR and preserving shared physical-site load groups, then using SLR
  groups for upper levels, with whole-SLR soft Pblocks for those leaf helpers
  (USER_SLR_ASSIGNMENT is ignored on leaf cells). Keeping a site's shared CE/reset and LUT inputs on
  one branch avoids breaking its existing packing relationships. Individual helper CR Pblocks
  are soft. Grouping uses the current physical placement as a locality hint;
  actual final placement, spill and timing must still be checked.
* Reset inherited FORCE_MAX_FANOUT properties. Editable ordinary nets use identity
  trees. The protected floating-point `*/inst/i_synth/*` family rejects direct
  ECO edits (Coretcl 2-76), so those drivers use FORCE_MAX_FANOUT=96 followed by
  native `phys_opt_design -force_replication_on_nets`. This is a conservative
  selector for the observed IP family, not a universal encryption-rights detector.
  Neither encryption rights nor protected netlist internals are manually changed.
  A native test reduced one protected 107-load LUT to five outputs with fanouts
  7, 39, 38, 7 and 16. Unsupported protected driver types are explicitly reported.
* Re-discover after physical optimization and repair newly created high-fanout
  nets. The initial pass introduces no FF or cycle latency. Each edit verifies
  every branch and exact original sink recovery through identity functions.
  Protect repaired root-net segments as well as helper outputs: 13 repaired
  driver names regrew in subsequent default placement in this experiment.
  Final cleanup uses `place_design -no_psip -no_bufg_opt` to preserve the
  distribution structure. Re-discover before native replication; store stable
  driver names separately from native pin objects used by connectivity queries.
  Re-editing an owned tree temporarily unlocks only its own root and helper
  inputs, proves exact connectivity, and restores protection before placement.
  The final protected-IP cleanup uses a physical target of 80 for margin;
  logical and physical acceptance remain at most 96 for ordinary networks.
* Exclude actual clock-load distribution and constants explicitly. BUFG-driven
  data/control with no clock sinks is included. Mixed clock/data networks are
  recorded as clock infrastructure, not silently claimed to meet the bound.
* Audit complete electrical nets independently using `audit_complete.tcl`; do
  not infer physical fanout from FORCE_MAX_FANOUT or logical pin count. A query
  on a single hierarchy segment can undercount loads on other segments, so all
  segments are expanded before collecting unique SITE_PIN inputs. To bound
  query cost, a union of several complete nets below the target certifies every
  member. Larger unions are divided until exact single-net counts are known.
  For fully ROUTED nets, all potential input pins attached to their routed
  nodes provide a faster conservative bound, including unused pins. Values
  above the target fall back to the exact segment union; other route states
  also use the segment union. A 107-net native comparison found no missing
  inputs and identical used-node/segment input sets. Deduplicate SITE_PIN NAME
  strings, because native query objects can repeat the same physical pin.
  Two apparent 97-load helpers were actually 55 and 56 unique physical inputs.
  Certificates distinguish conservative bounds from exact counts. Final DCP
  reopening repeats logical discovery and covers every nonconstant net with a
  physical certificate or an explicit clock exception. SITE_PIN filtering uses
  DIRECTION only; IS_LEAF is a logical PIN property. The user's strict <100 gate
  and the internal <=96 margin are reported separately.

## Validation scope

`smoke.tcl` tests independent BRAM outputs, nested replica names, BUFG controls,
synchronous resets, true clock/constant exclusions, spatial multilevel trees,
flatten/rebuild exact connectivity, branch/root limits and checkpoint reopen.
It checks a 3-load bound to exercise multiple levels on a small design.

Preserving original driver functions, exact sink sets, and identity LUT functions
proves the local combinational rewrite. It does not constitute full sequential
formal equivalence between the original post-opt design and all prior Vivado
optimizations. Routing, setup, hold and final fanout remain separate measured
acceptance gates. Unmet gates are reported as annotations per user instruction.

The new logic adds combinational delay and load-specific control nets; lowering
fanout is not a guarantee of better WNS. No pipeline or HLS/II change is made.

## Reference

[AMD UG986, 2022.2 edition, "Step 5: Implementing the ECO Changes"](https://docs.amd.com/r/2022.2-English/ug986-vivado-tutorial-implementation/Step-5-Implementing-the-ECO-Changes) documents
incremental placement/routing following cell/net edits to an existing checkpoint.
[UG912 FORCE_MAX_FANOUT](https://docs.amd.com/r/2023.2-English/ug912-vivado-properties/FORCE_MAX_FANOUT) specifies a physical fanout target for FF/LUT replication;
it is not a complete logical-fanout or all-generation audit.
[UG835 place_design](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/place_design)
documents `-no_psip` as disabling physical synthesis inside the placer.
