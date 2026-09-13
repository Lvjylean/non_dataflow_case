#!/usr/bin/env bash
set -eo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
case "$1" in vta|cnna) ;; *) exit 2;; esac
out="$BENCH_ROOT/runs/$2"
mkdir "$out"
cd "$out"
source /home/lduac/Software/Xilinx/Vitis_HLS/2023.2/settings64.sh
set +e
if [ "$1" = vta ]; then
 python3 "$BENCH_ROOT/scripts/vta_config.py" "$BENCH_ROOT" "${VTA_CONFIG_JSON:-$BENCH_ROOT/upstream/tvm-vta/config/vta_config.json}" || exit 2
 /usr/bin/time -v vitis_hls -f "$BENCH_ROOT/scripts/vta_hls.tcl" > run.log 2>&1
else
 /usr/bin/time -v vitis_hls -f "$BENCH_ROOT/scripts/cnna_probe.tcl" > run.log 2>&1
fi
code=$?
printf '%s\n' "$code" > exit_code
exit "$code"
