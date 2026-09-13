#!/usr/bin/env bash
set -eo pipefail
export BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
kind="$2"
package="$BENCH_ROOT/runs/$3/${kind}_kernel.xo"
test -s "$package"
python3 "$BENCH_ROOT/scripts/audit_platform_package.py" "$BENCH_ROOT/runs/$3"
out="$BENCH_ROOT/runs/$1"
mkdir "$out"
cd "$out"
mkdir input_scripts
cp "$BENCH_ROOT/scripts/run_platform_link.sh" "$BENCH_ROOT/scripts/platform_postroute.tcl" "$BENCH_ROOT/scripts/reports.tcl" "$BENCH_ROOT/scripts/dual_slr_floorplan.tcl" input_scripts/
sha256sum "$package" > package_input.sha256
cp "$BENCH_ROOT/runs/$3/interface_audit.json" .
export BENCH_REPORT_DIR="$out/physical"
cp "$BENCH_ROOT/scripts/dual_slr_floorplan.tcl" .
cp "$BENCH_ROOT/scripts/platform_postroute.tcl" .
{
  echo '[connectivity]'
  if [ "$kind" = cnna ]; then
    count="${CNNA_CUS:-6}"
    case "$count" in 6|8) ;; *) exit 2;; esac
    echo "nk=cnna_kernel:$count"
    for ((i=1;i<=count;i++)); do
      if [ "$i" -le "$((count/2))" ]; then slr=2; else slr=3; fi
      echo "slr=cnna_kernel_$i:SLR$slr"
      echo "sp=cnna_kernel_$i.M_AXI_GMEM:DDR[$slr]"
    done
  else
    echo 'nk=vta64_kernel:1'
    echo 'sp=vta64_kernel_1.M_AXI_GMEM:DDR[2]'
  fi
  echo '[vivado]'
  echo 'synth.jobs=4'
  echo 'impl.jobs=4'
  echo 'prop=run.impl_1.STEPS.PHYS_OPT_DESIGN.IS_ENABLED=true'
  echo "prop=run.impl_1.STEPS.ROUTE_DESIGN.TCL.POST=$out/platform_postroute.tcl"
  if [ "$kind" != cnna ]; then
    echo "prop=run.impl_1.STEPS.OPT_DESIGN.TCL.POST=$out/dual_slr_floorplan.tcl"
  fi
} > link.cfg
source /home/lduac/Software/Xilinx/Vitis/2023.2/settings64.sh
cache="$BENCH_ROOT/ip_cache/u250_2023_2"
mkdir -p "$cache"
(
  flock -x 9
  for previous in cnna8_platform_20260913_03 cnna6_platform_20260913_01 vta64_platform_20260913_01; do
    if [ -d "$BENCH_ROOT/runs/$previous/.ipcache" ]; then
      rsync -a --ignore-existing "$BENCH_ROOT/runs/$previous/.ipcache/" "$cache/"
    fi
  done
) 9>"$BENCH_ROOT/ip_cache/seed.lock"
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
 --kernel_frequency 100 --config link.cfg --remote_ip_cache "$cache" --save-temps --temp_dir build --log_dir logs --report_dir reports \
 "${repo_args[@]}" -o "${kind}.xclbin" "$package" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
if [ "$code" -eq 0 ]; then
  test -s "${kind}.xclbin" || exit 91
  /opt/xilinx/xrt/bin/xclbinutil --input "${kind}.xclbin" --info > configuration_info.txt 2>&1 || exit 92
  sha256sum "${kind}.xclbin" > configuration.sha256 || exit 91
  bash "$BENCH_ROOT/scripts/run_platform_verify.sh" "$1"
  exit $?
fi
exit "$code"
