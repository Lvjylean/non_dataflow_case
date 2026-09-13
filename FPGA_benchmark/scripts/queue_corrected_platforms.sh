#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
obsolete=(cnna8_platform_20260913_03 cnna6_platform_20260913_01 vta64_platform_20260913_01)
while true; do
  pending=0
  for run in "${obsolete[@]}"; do
    if [ ! -f "runs/$run/exit_code" ]; then pending=1; fi
  done
  if [ "$pending" -eq 0 ]; then break; fi
  sleep 30
done
# Existing obsolete runs finish or are explicitly terminated by the user-authorized action.
# This queue never terminates a process.
bash scripts/run_platform_link.sh vta64_platform_20260913_02 vta64 vta64_package_20260913_03 &
vta_job=$!
bash scripts/run_platform_link.sh cnna6_platform_20260913_02 cnna cnna_package_20260913_05 &
cnna_job=$!
set +e
wait "$vta_job"; vta_code=$?
wait "$cnna_job"; cnna_code=$?
printf 'VTA exit=%s CNNA exit=%s\n' "$vta_code" "$cnna_code"
if [ "$vta_code" -ne 0 ] || [ "$cnna_code" -ne 0 ]; then exit 1; fi
