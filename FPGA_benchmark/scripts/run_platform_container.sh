#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
run_id="$1"; kind="$2"; recovery="$root/runs/$3"; original="$root/runs/$4"
test -f "$recovery/exit_code"
test -s "$recovery/build/link/int/partial.bit"
cmp "$original/package_input.sha256" "$recovery/package_input.sha256"
out="$root/runs/$run_id"
mkdir "$out"
cd "$out"
cp "$root/scripts/run_platform_container.sh" .
cp "$recovery/"{interface_audit.json,package_input.sha256,recovery_source.tsv} .
mkdir metadata
cp "$recovery/build/link/int/"{sdsl.dat,xclbin_orig.xml,appendSection.rtd} metadata/
cp "$recovery/build/link/int/${kind}_xml.rtd" "$recovery/build/link/int/${kind}_build.rtd" metadata/
cp "$original/build/link/int/address_map.xml" metadata/
sha256sum "$recovery/build/link/int/partial.bit" "$original/build/link/int/address_map.xml" > packaging_inputs.sha256
set +u
source /home/lduac/Software/Xilinx/Vitis/2023.2/settings64.sh
set -u
trap 'code=$?; printf "%s\n" "$code" > exit_code' EXIT
exec > run.log 2>&1
date -Is
# Reproduce the native rtdgen cf2sw invocation from the recorded v++ log.
cf2sw -a metadata/address_map.xml -sdsl metadata/sdsl.dat -xclbin metadata/xclbin_orig.xml \
  -rtd "metadata/${kind}.rtd" -o "metadata/${kind}.xml"
# Retain all runtime sections. The optional IDE system diagram is omitted
# because its pre-implementation address/resource fields are not authoritative.
xclbinutil --add-section "BITSTREAM:RAW:$recovery/build/link/int/partial.bit" \
  --target hw --key-value SYS:dfx_enable:true \
  --add-section ":JSON:metadata/${kind}.rtd" --append-section :JSON:metadata/appendSection.rtd \
  --add-section "CLOCK_FREQ_TOPOLOGY:JSON:metadata/${kind}_xml.rtd" \
  --add-section "BUILD_METADATA:JSON:metadata/${kind}_build.rtd" \
  --add-section "EMBEDDED_METADATA:RAW:metadata/${kind}.xml" \
  --key-value SYS:PlatformVBNV:xilinx_u250_gen3x16_xdma_4_1_202210_1 --output "${kind}.xclbin"
/opt/xilinx/xrt/bin/xclbinutil --input "${kind}.xclbin" --info > configuration_info.txt
sha256sum "${kind}.xclbin" > configuration.sha256
for section in MEM_TOPOLOGY IP_LAYOUT CONNECTIVITY CLOCK_FREQ_TOPOLOGY PARTITION_METADATA; do
  /opt/xilinx/xrt/bin/xclbinutil --input "${kind}.xclbin" --dump-section "$section:JSON:$section.json"
done
/opt/xilinx/xrt/bin/xclbinutil --input "${kind}.xclbin" --dump-section BITSTREAM:RAW:container_payload.bit
cmp container_payload.bit "$recovery/build/link/int/partial.bit"
printf 'container_bitstream_matches_source\t1\n' > container_validation.tsv
date -Is
