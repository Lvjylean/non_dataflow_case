#!/usr/bin/env bash
set -euo pipefail
case_dir="$(cd "$(dirname "$0")" && pwd)"
: "${1:?Usage: bash launch.sh /absolute/path/to/a/new/run-directory}"
[[ "$1" = /* ]] || { echo "Output directory must be absolute" >&2; exit 1; }
[[ ! -e "$1" ]] || { echo "Output directory already exists" >&2; exit 1; }
mkdir -p "$1"
cp "$case_dir/run.tcl" "$1/run.tcl"
source /home/lduac/Software/Xilinx/Vitis_HLS/2023.2/settings64.sh
cd "$1"
ulimit -s unlimited
vitis_hls -f run.tcl 2>&1 | tee run.log
