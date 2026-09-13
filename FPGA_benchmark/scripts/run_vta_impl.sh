#!/usr/bin/env bash
set -eo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export VTA_HLS_RUN="$BENCH_ROOT/runs/$2"
out="$BENCH_ROOT/runs/$1"
mkdir "$out"
cd "$out"
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v vivado -mode batch -source "$BENCH_ROOT/scripts/vta_impl.tcl" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
if [ "$code" -ne 0 ]; then exit "$code"; fi
mkdir reopen
cd reopen
/usr/bin/time -v vivado -mode batch -source "$BENCH_ROOT/scripts/reopen.tcl" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
exit "$code"
