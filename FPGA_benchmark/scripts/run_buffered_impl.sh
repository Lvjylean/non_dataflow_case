#!/usr/bin/env bash
set -eo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export BASE_DCP="$BENCH_ROOT/runs/$2/post_synth.dcp"
mkdir "$BENCH_ROOT/runs/$1"
cd "$BENCH_ROOT/runs/$1"
sha256sum "$BASE_DCP" > baseline_before.sha256
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v vivado -mode batch -source "$BENCH_ROOT/scripts/buffered_impl.tcl" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
sha256sum "$BASE_DCP" > baseline_after.sha256
cmp baseline_before.sha256 baseline_after.sha256 || exit 90
if [ "$code" -ne 0 ]; then exit "$code"; fi
mkdir reopen
cd reopen
/usr/bin/time -v vivado -mode batch -source "$BENCH_ROOT/scripts/reopen.tcl" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
exit "$code"
