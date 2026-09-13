#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
source /home/lduac/Software/Xilinx/Vitis_HLS/2023.2/settings64.sh
ulimit -s unlimited
vitis_hls -version > tool_version.txt 2>&1
python3 -u run_batch.py
