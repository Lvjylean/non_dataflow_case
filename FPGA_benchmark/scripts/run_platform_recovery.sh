#!/usr/bin/env bash
set -euo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
run_id="$1"
kind="$2"
source_run="$3"
package_run="$4"
original="$BENCH_ROOT/runs/$source_run"
checkpoint="$original/physical/routed.dcp"
package="$BENCH_ROOT/runs/$package_run/${kind}_kernel.xo"
test -s "$checkpoint"
test -s "$package"
python3 "$BENCH_ROOT/scripts/audit_platform_package.py" "$BENCH_ROOT/runs/$package_run"
out="$BENCH_ROOT/runs/$run_id"
mkdir "$out"
cd "$out"
mkdir input_scripts physical
cp "$BENCH_ROOT/scripts/"{run_platform_recovery.sh,platform_reopen.tcl,platform_postroute.tcl,reports.tcl} input_scripts/
cp "$BENCH_ROOT/runs/$package_run/interface_audit.json" .
sha256sum "$package" > package_input.sha256
sha256sum "$checkpoint" > checkpoint_before.sha256
printf 'source_run\t%s\nsource_checkpoint\t%s\npackage_run\t%s\n' "$source_run" "$checkpoint" "$package_run" > recovery_source.tsv
# Keep the source immutable while retaining an explicit audit target.
ln -s "$checkpoint" physical/routed.dcp
sed '/^prop=/d' "$original/link.cfg" > link.cfg
export AUDIT_DCP="$checkpoint"
export BENCH_REPORT_DIR="$out/physical"
export SKIP_CHECKPOINT_WRITE=1
# Tool settings are not guaranteed to be compatible with nounset.
set +u
source /home/lduac/Software/Xilinx/Vitis/2023.2/settings64.sh
set -u
repo_args=()
if [ "$kind" = cnna ]; then
  repo_args+=(--user_ip_repo_paths "$BENCH_ROOT/runs/cnna_dma_hls_20260913_01/cnna_dma_hls/soln/impl/ip")
else
  for stage in fetch load compute store; do
    repo_args+=(--user_ip_repo_paths "$BENCH_ROOT/runs/vta64_hls_20260913_02/vta_$stage/soln/impl/ip")
  done
fi
set +e
/usr/bin/time -v v++ -l -t hw --platform /opt/xilinx/platforms/xilinx_u250_gen3x16_xdma_4_1_202210_1/xilinx_u250_gen3x16_xdma_4_1_202210_1.xpfm \
  --kernel_frequency 100 --config link.cfg --reuse_impl "$checkpoint" \
  --save-temps --temp_dir build --log_dir logs --report_dir reports \
  "${repo_args[@]}" -o "${kind}.xclbin" "$package" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
set -e
# Audit even when packaging fails; do not conflate the two outcomes.
/usr/bin/time -v vivado -mode batch -source "$out/input_scripts/platform_reopen.tcl" > physical/run.log 2>&1 &
audit_pid=$!
set +e
wait "$audit_pid"
audit_code=$?
printf '%s\n' "$audit_code" > physical/exit_code
set -e
if [ "$code" -eq 0 ]; then
  test -s "${kind}.xclbin"
  /opt/xilinx/xrt/bin/xclbinutil --input "${kind}.xclbin" --info > configuration_info.txt 2>&1
  sha256sum "${kind}.xclbin" > configuration.sha256
fi
if [ "$audit_code" -eq 0 ]; then
  bash "$BENCH_ROOT/scripts/run_platform_verify.sh" "$run_id"
fi
sha256sum "$checkpoint" > checkpoint_after.sha256
cmp checkpoint_before.sha256 checkpoint_after.sha256
printf 'packaging_exit\t%s\naudit_exit\t%s\n' "$code" "$audit_code" > recovery_result.tsv
exit "$code"
