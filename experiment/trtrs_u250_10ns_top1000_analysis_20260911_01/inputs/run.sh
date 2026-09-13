#!/usr/bin/env bash
set -eo pipefail
cd "$RUN_DIR"
export INPUT_DCP=/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/trtrs_u250_10ns_maxfanout256_round2_20260911_01/routed.dcp
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
sha256sum "$INPUT_DCP" > input_before.sha256
set +e
/usr/bin/time -v -o runtime.txt vivado -mode batch -log vivado.log -journal vivado.jou -source inputs/run.tcl > console.log 2>&1
rc=$?
sha256sum -c input_before.sha256 > input_after.txt
hash_rc=$?
if [ "$hash_rc" -ne 0 ]; then rc=$hash_rc; fi
printf '%s\n' "$rc" > exit_code.txt
exit "$rc"
