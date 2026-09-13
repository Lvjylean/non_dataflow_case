#!/usr/bin/env bash
set -eo pipefail
: "${HLS_OUTPUT_DIR:?Set a fresh absolute HLS output directory}"
source /home/lduac/Software/Xilinx/Vitis_HLS/2023.2/settings64.sh
vitis_hls -f "/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision_tvl1_optical_flow_1024x1024_npc2__LUT_59p6pctSLR__20260911_v04/rerun.tcl"
