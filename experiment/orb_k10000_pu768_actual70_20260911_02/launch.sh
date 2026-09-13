#!/usr/bin/env bash
set -eo pipefail
cd "$RUN_DIR"
trap 'rc=$?; printf "%s\n" "$rc" > exit_code.txt' EXIT
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v -o implementation_time.txt vivado -mode batch -log vivado.log -journal vivado.jou -source inputs/run.tcl > console.log 2>&1
rc=$?;printf '%s\n' "$rc" > implementation_exit_code.txt
set -e
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
printf 'REOPEN %s\n' "$(date -Is)" > phase.txt
set +e
/usr/bin/time -v -o reopen_time.txt vivado -mode batch -log reopen.log -journal reopen.jou -source inputs/reopen.tcl > reopen_console.log 2>&1
rc=$?;printf '%s\n' "$rc" > reopen_exit_code.txt
exit "$rc"
