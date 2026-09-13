#!/usr/bin/env bash
set -eo pipefail
cd "$RUN_DIR"
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v -o audit_final_time.txt vivado -mode batch -log audit_final.log -journal audit_final.jou -source inputs/audit_final.tcl > audit_final_console.log 2>&1
rc=$?
printf '%s\n' "$rc" > audit_final_exit_code.txt
exit "$rc"
