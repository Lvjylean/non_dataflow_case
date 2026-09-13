#!/usr/bin/env bash
set -eo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
export AUDIT_DCP="$root/runs/$2/physical/routed.dcp"
test -s "$AUDIT_DCP"
out="$root/runs/$1"
mkdir "$out"
cd "$out"
cp "$root/scripts/resource_review.tcl" "$root/scripts/run_resource_review.sh" .
sha256sum "$AUDIT_DCP" > checkpoint_before.sha256
source /home/lduac/Software/Xilinx/Vivado/2023.2/settings64.sh
set +e
/usr/bin/time -v vivado -mode batch -source resource_review.tcl > run.log 2>&1
code=$?
sha256sum "$AUDIT_DCP" > checkpoint_after.sha256
cmp checkpoint_before.sha256 checkpoint_after.sha256 || code=90
printf '%s\n' "$code" > exit_code
exit "$code"
