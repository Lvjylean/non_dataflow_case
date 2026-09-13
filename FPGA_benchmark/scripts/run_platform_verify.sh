#!/usr/bin/env bash
set -eo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export AUDIT_DCP="$BENCH_ROOT/runs/$1/physical/routed.dcp"
test -s "$AUDIT_DCP"
export BENCH_REPORT_DIR="$BENCH_ROOT/runs/$1/physical/reopen"
export FAST_REOPEN=1
mkdir "$BENCH_REPORT_DIR"
cd "$BENCH_REPORT_DIR"
mkdir input_scripts
cp "$BENCH_ROOT/scripts/"{platform_reopen.tcl,platform_postroute.tcl,reports.tcl,reports_reopen.tcl,run_platform_verify.sh} input_scripts/
sha256sum input_scripts/* > input_scripts.sha256
sha256sum "$AUDIT_DCP" > checkpoint_before.sha256
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v vivado -mode batch -source "$BENCH_REPORT_DIR/input_scripts/platform_reopen.tcl" > run.log 2>&1
code=$?
sha256sum "$AUDIT_DCP" > checkpoint_after.sha256
cmp checkpoint_before.sha256 checkpoint_after.sha256 || code=90
printf '%s\n' "$code" > exit_code
exit "$code"
