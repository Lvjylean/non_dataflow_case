#!/usr/bin/env bash
set -eo pipefail
cd "$RUN_DIR"
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v -o implementation_time.txt vivado -mode batch -log vivado.log -journal vivado.jou -source inputs/run.tcl > console.log 2>&1
rc=$?
printf '%s\n' "$rc" > implementation_exit_code.txt
if [ "$rc" -eq 0 ]; then
  /usr/bin/time -v -o reopen_time.txt vivado -mode batch -log reopen.log -journal reopen.jou -source inputs/reopen.tcl > reopen_console.log 2>&1
  rc=$?
  printf '%s\n' "$rc" > reopen_exit_code.txt
fi
printf '%s\n' "$rc" > exit_code.txt
exit "$rc"
