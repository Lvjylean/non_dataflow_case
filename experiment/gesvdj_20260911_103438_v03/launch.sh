#!/usr/bin/env bash
set -eo pipefail
: "${HLS_OUTPUT_DIR:?Set a fresh absolute HLS output directory}"
source /home/lduac/Software/Xilinx/Vitis_HLS/2023.2/settings64.sh
vitis_hls -f "/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gesvdj_20260911_103438_v03/rerun.tcl"
