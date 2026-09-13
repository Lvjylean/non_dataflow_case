#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
base=/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/orb_u250_5ns_fanout256_resetfix_20260911_02
for pu in 64 128 256; do
  export SOURCE_RUN="$base/pu$pu"
  export AUDIT_DIR="$PWD/pu$pu"
  mkdir "$AUDIT_DIR"
  while [ ! -f "$SOURCE_RUN/exit_code.txt" ]; do sleep 60; done
  if [ "$(cat "$SOURCE_RUN/exit_code.txt")" != 0 ]; then
    printf 'Source run failed\n' > "$AUDIT_DIR/source_failed.txt"
    continue
  fi
  set +e
  vivado -mode batch -log "$AUDIT_DIR/vivado.log" -journal "$AUDIT_DIR/vivado.jou" -source audit.tcl > "$AUDIT_DIR/console.log" 2>&1
  rc=$?
  set -e
  printf '%s\n' "$rc" > "$AUDIT_DIR/exit_code.txt"
done
