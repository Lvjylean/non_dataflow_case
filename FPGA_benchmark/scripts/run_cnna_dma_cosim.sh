#!/usr/bin/env bash
set -eo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir "$BENCH_ROOT/runs/$1"
cd "$BENCH_ROOT/runs/$1"
source /home/lduac/Software/Xilinx/Vitis_HLS/2023.2/settings64.sh
set +e
/usr/bin/time -v vitis_hls -f "$BENCH_ROOT/scripts/cnna_dma_cosim.tcl" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
exit "$code"
