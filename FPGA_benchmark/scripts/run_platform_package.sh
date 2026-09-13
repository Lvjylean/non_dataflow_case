#!/usr/bin/env bash
set -eo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export CORE_KIND="$2"
export VTA_HLS_RUN="${VTA_HLS_RUN:-$BENCH_ROOT/runs/vta64_hls_20260913_02}"
export CNNA_DMA_RUN="$BENCH_ROOT/runs/cnna_dma_hls_20260913_01"
mkdir "$BENCH_ROOT/runs/$1"
cd "$BENCH_ROOT/runs/$1"
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v vivado -mode batch -source "$BENCH_ROOT/scripts/platform_kernel.tcl" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
exit "$code"
