#!/usr/bin/env bash
set -euo pipefail
local_root="$(cd "$(dirname "$0")/.." && pwd)"
server_root=/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark
mkdir -p "$local_root/reports"
rsync -az --prune-empty-dirs \
 --exclude='project/' --exclude='build/' --exclude='.ipcache/' --exclude='packaged/' --exclude='logs/' --exclude='*_detail.rpt' --exclude='.Xil/' --exclude='.autopilot/' \
 --include='*/' --include='*.rpt' --include='*_csynth.xml' \
 --include='MEM_TOPOLOGY.json' --include='IP_LAYOUT.json' --include='CONNECTIVITY.json' --include='CLOCK_FREQ_TOPOLOGY.json' --include='PARTITION_METADATA.json' --include='packaging_inputs.sha256' --include='input_scripts.sha256' \
 --include='run.log' --include='exit_code' --include='*.tsv' --include='configuration_info.txt' --include='interface_audit.json' --include='configuration.sha256' --include='package_input.sha256' --include='kernel.xml' --include='test_overlay.json' --include='link.cfg' --include='*_nets.txt' \
 --include='reopened.txt' --include='*_unavailable.txt' \
 --include='checkpoint_*.sha256' --include='baseline_*.sha256' --include='clock_region_primitives.tsv' --include='audit_summary.txt' --include='clock_route_status.txt' --include='clock_net_properties.txt' --include='audit_exit_code' --include='input_scripts_manifest.json' --include='wrapper_port_audit.json' --include='buffered_wrapper.v' --include='config.json' --include='config.tcl' --exclude='*' \
 "eda070:$server_root/runs/" "$local_root/reports/"
