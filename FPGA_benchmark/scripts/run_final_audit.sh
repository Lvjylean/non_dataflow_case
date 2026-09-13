#!/usr/bin/env bash
set -eo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export AUDIT_DCP="$BENCH_ROOT/runs/$1/routed.dcp"
mkdir "$BENCH_ROOT/runs/$1/route_diagnostic"
cd "$BENCH_ROOT/runs/$1/route_diagnostic"
sha256sum "$AUDIT_DCP" > checkpoint_before.sha256
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v vivado -mode batch -source "$BENCH_ROOT/scripts/final_audit.tcl" > run.log 2>&1
code=$?
if [ "$code" -eq 0 ]; then python3 "$BENCH_ROOT/scripts/aggregate_regions.py" || code=91; fi
sha256sum "$AUDIT_DCP" > checkpoint_after.sha256
cmp checkpoint_before.sha256 checkpoint_after.sha256 || code=90
printf '%s\n' "$code" > audit_exit_code
exit "$code"
