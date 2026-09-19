# highfanout1: placed identity-tree baseline

This branch freezes the source of the existing fanout96/quick implementation
before the placement-native FF/LUT redesign. The entry point is
`balanced_implementation/implement_quick.tcl`; `seed_fast.tcl` supplies its first
placement. `run_fast.py` orchestrates implementation and independent reopening.
The companion `source_manifest.json` lists the exact original source bytes.

The baseline discovers live electrical networks, constructs identity LUT trees
using placed CR/SITE groups, places the edited design again, applies native
replication to protected floating-point drivers, then routes and audits.
Construction targets 96 logical loads; final user acceptance is strictly fewer
than 100. Physical site-pin counts are distinct. Clock/constant exceptions and
unmet ordinary-network bounds must be reported explicitly.

The source publication includes the implementation/readback dependency closure,
synthetic native smoke scripts and pure Tcl tests. It contains no new DCP,
netlist-derived membership/connectivity exports, run logs or experiment artifacts.
Run inputs remain external and immutable. No physical experiment was rerun for
this publication. The two local pure Tcl tests pass; historical physical results
do not certify the forthcoming native implementation.

Local checks:

```sh
tclsh FPGA_benchmark/netlist_hier_floorplan/fanout96/test_fast_plan.tcl
tclsh FPGA_benchmark/netlist_hier_floorplan/fanout96/test_quick.tcl
```

The existing `balanced_implementation/README.md` also describes historical serial
and report utilities outside this source-only snapshot. Use its quick-flow
section and the entry points above for this baseline.
