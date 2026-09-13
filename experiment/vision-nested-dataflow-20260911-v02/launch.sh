#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
source /home/lduac/Software/Xilinx/Vitis_HLS/2023.2/settings64.sh
python3 run_batch.py
