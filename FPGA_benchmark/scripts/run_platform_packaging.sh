#!/usr/bin/env bash
set -euo pipefail
echo 'Superseded: relocated --from_step can restart VPL. Use run_platform_container.sh.' >&2
exit 2
root="$(cd "$(dirname "$0")/.." && pwd)"
run_id="$1"; kind="$2"; recovery="$root/runs/$3"; original="$root/runs/$4"; package_run="$5"
test -s "$recovery/build/link/int/partial.bit"
test -f "$recovery/exit_code"
test -s "$original/build/link/int/address_map.xml"
cmp "$original/package_input.sha256" "$recovery/package_input.sha256"
out="$root/runs/$run_id"
mkdir "$out"
cp "$recovery/"{link.cfg,interface_audit.json,package_input.sha256,recovery_source.tsv} "$out/"
cp "$root/scripts/run_platform_packaging.sh" "$out/"
# Clone tool state, never edit the failed recovery run or its active audit.
cp -a "$recovery/build" "$out/"
python3 - "$recovery" "$out" <<'PY'
import sys
from pathlib import Path
old,new=sys.argv[1:]
for p in (Path(new)/'build').rglob('*'):
    if not p.is_file() or p.is_symlink() or p.suffix in {'.bit','.dcp','.zip','.pb'}:
        continue
    data=p.read_bytes()
    if b'\0' in data:
        continue
    try: content=data.decode('utf-8')
    except UnicodeDecodeError: continue
    if old in content: p.write_text(content.replace(old,new))
PY
cp "$original/build/link/int/address_map.xml" "$out/build/link/int/address_map.xml"
cd "$out"
sha256sum "$recovery/build/link/int/partial.bit" "$original/build/link/int/address_map.xml" > packaging_inputs.sha256
set +u
source /home/lduac/Software/Xilinx/Vitis/2023.2/settings64.sh
set -u
set +e
/usr/bin/time -v v++ -l -t hw --platform /opt/xilinx/platforms/xilinx_u250_gen3x16_xdma_4_1_202210_1/xilinx_u250_gen3x16_xdma_4_1_202210_1.xpfm \
  --kernel_frequency 100 --config link.cfg --from_step rtdgen \
  --save-temps --temp_dir build --log_dir logs --report_dir reports \
  -o "${kind}.xclbin" "$root/runs/$package_run/${kind}_kernel.xo" > run.log 2>&1
code=$?
printf '%s\n' "$code" > exit_code
set -e
if [ "$code" -eq 0 ]; then
  /opt/xilinx/xrt/bin/xclbinutil --input "${kind}.xclbin" --info > configuration_info.txt 2>&1
  sha256sum "${kind}.xclbin" > configuration.sha256
  for section in MEM_TOPOLOGY IP_LAYOUT CONNECTIVITY CLOCK_FREQ_TOPOLOGY PARTITION_METADATA; do
    /opt/xilinx/xrt/bin/xclbinutil --input "${kind}.xclbin" --dump-section "$section:JSON:$section.json" >> container_audit.log 2>&1
  done
  /opt/xilinx/xrt/bin/xclbinutil --input "${kind}.xclbin" --dump-section BITSTREAM:RAW:container_payload.bit >> container_audit.log 2>&1
  cmp container_payload.bit "$recovery/build/link/int/partial.bit"
  printf 'container_bitstream_matches_source\t1\n' > container_validation.tsv
fi
exit "$code"
