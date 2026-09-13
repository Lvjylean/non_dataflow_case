#!/usr/bin/env bash
set -eo pipefail
cd "$RUN_DIR"
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
sha256sum /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vivado-trtrs-baseline-10ns-20260911-01/post_synth.dcp > baseline_dcp_before.sha256
set +e
/usr/bin/time -v -o preflight_time.txt vivado -mode batch -source inputs/preflight.tcl -log preflight.log -journal preflight.jou > preflight_console.log 2>&1
rc=$?
printf '%s\n' "$rc" > preflight_exit_code.txt
sha256sum -c baseline_dcp_before.sha256 > baseline_dcp_after.txt
exit "$rc"
