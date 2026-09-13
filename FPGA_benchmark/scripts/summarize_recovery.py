"""Produce a reproducible compact report from recovery and container evidence."""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from summarize import route

root = Path(__file__).resolve().parents[1]
reports = root / 'reports'
server = '/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs'
variants = [('VTA64', 'vta64', 'vta64_resource_review_20260913_01'), ('CNNA6', 'cnna6', None)]
results = []
resource_rows = []
for label, prefix, extra in variants:
    recovery = prefix + '_recovery_20260913_01'
    container = prefix + '_container_20260913_01'
    subprocess.run([sys.executable, str(root/'scripts/validate_container.py'), container], check=True, capture_output=True)
    args = [sys.executable, str(root/'scripts/validate_platform.py'), recovery, container]
    if extra:
        args.append(extra)
    subprocess.run(args, check=True, capture_output=True)
    data = json.loads((reports/recovery/'platform_validation.json').read_text())
    totals = {k: [0.0]*4 for k in ['CLB LUTs', 'CLB Registers', 'Block RAM Tile', 'DSPs', 'URAM']}
    for name, resources in data['native_slr_resources'].items():
        kernel = re.search(r'(?:vta64|cnna)_kernel_\d+', name).group()
        for key in totals:
            totals[key] = [a+b for a,b in zip(totals[key], resources[key])]
        for slr in range(4):
            resource_rows.append([label, kernel, 'SLR'+str(slr)] + [resources[k][slr] for k in totals])
    results.append((label, prefix, recovery, container, data, totals))
with (reports/'accelerator_resources_by_slr.tsv').open('w') as output:
    writer = csv.writer(output, delimiter='\t')
    writer.writerow(['variant', 'kernel', 'slr', 'lut', 'ff', 'bram36_equivalent', 'dsp', 'uram'])
    writer.writerows(resource_rows)

lines = ['# U250 检查点恢复、产物与独立验证', '',
         '资源以 Vivado 原生按核、按 SLR 的 utilization 表为准，不含平台 shell。VTA64 为单个 64×64 引擎；CNNA6 为六个独立引擎的多核扩展。布局约束指定 SLR2/SLR3。', '',
         '| Case | 当前验收状态 | XCLBIN 容器检查 |', '|---|---|---|']
for label, prefix, recovery, container, data, totals in results:
    lines.append(f'| {label} | {data["status"]} | PASS |')
lines += ['', 'REVIEW_REQUIRED 表示产物、布线、重开一致性及数值时序检查已通过，但约束覆盖、CDC 和 methodology 告警尚需审查；不等于最终验收通过。PENDING_OR_FAILED 表示证据尚未齐全或有检查未通过。', '',
          '## 加速器实际资源', '', '| Case | SLR | LUT | FF | BRAM36 等效 | DSP | URAM |', '|---|---|---:|---:|---:|---:|---:|']
for label, prefix, recovery, container, data, totals in results:
    for slr in [2,3]:
        cells = [f'{totals[k][slr]:g}' for k in totals]
        lines.append('| '+ ' | '.join([label, 'SLR'+str(slr)] + cells) + ' |')
lines += ['', '各核明细见 [TSV](accelerator_resources_by_slr.tsv)。早期 accelerator_regions.tsv 中基于 REF_NAME 的 DSP/RAM 列会漏计展开的原语，不能用于资源总量；仅使用其 primitive_count 验证位置。原始报告保留以追踪这一统计问题。', '',
          '## 布线与跨 SLR 连接', '', '| Case | 已布线 / 可布线 nets | 路由错误 | 全平台 SLL 使用量 |', '|---|---:|---:|---:|']
for label, prefix, recovery, container, data, totals in results:
    folder=reports/recovery/'physical'
    r=route((folder/'route_status.rpt').read_text())
    match=re.search(r'\| Total SLLs Used\s*\|\s*(\d+)',(folder/'slr_utilization.rpt').read_text())
    lines.append(f'| {label} | {r["routed"]} / {r["routable"]} | {r["errors"]} | {match[1] if match else "待生成"} |')
lines += ['', '此处 SLL 为全平台统计，包含 shell 和接口跨 SLR 连接；不等同于计算核内部跨 SLR 数量。方向性连接矩阵见各 physical/slr_utilization.rpt。', '',
          '## 全平台时序', '', '| Case | 内核数据时钟 | WNS (ns) | WHS (ns) | WPWS (ns) | TNS / THS / TPWS (ns) | Setup / Hold / 脉宽失败端点 |', '|---|---:|---:|---:|---:|---|---|']
for label, prefix, recovery, container, data, totals in results:
    t = data['timing_summary']
    if t:
        lines.append(f'| {label} | 100 MHz | {t["wns_ns"]:+.3f} | {t["whs_ns"]:+.3f} | {t["wpws_ns"]:.3f} | {t["tns_ns"]:g} / {t["ths_ns"]:g} / {t["tpws_ns"]:g} | {t["setup_failing_endpoints"]} / {t["hold_failing_endpoints"]} / {t["pulse_failing_endpoints"]} |')
lines += ['', '这些是多时钟完整平台的最差裕量，不能用来直接换算计算核 Fmax。完整 min/max/pulse-width 汇总和端点总数保存在每个 platform_validation.json 中。', '',
          '## 剩余审查与验证证据', '']
for label, prefix, recovery, container, data, totals in results:
    pending = [key for key,value in data['checks'].items() if not value]
    coverage = data['timing_coverage']['root']
    lines += [f'- **{label}**：内部未约束端点 {coverage.get("unconstrained_internal_endpoints", "待生成")}；未设置 input/output delay 的端口分别为 {coverage.get("no_input_delay", "待生成")}/{coverage.get("no_output_delay", "待生成")}。',
              f'  [机器检查结果]({recovery}/platform_validation.json)；未通过或待审项：'+', '.join(pending)+'.']
lines += ['', '边界端口涉及平台 PERST、DDR reset、QSFP、UART 和管理接口。methodology/CDC 涉及平台时钟定义、时钟门控、PCIe、JTAG 等；未添加一刀切 false path，也未自动豁免这些发现。详细 CDC 报告保留端点与 waiver 标识。', '',
          '## 服务器产物与来源', '']
for label, prefix, recovery, container, data, totals in results:
    kind = 'vta64' if prefix == 'vta64' else 'cnna'
    digest = (reports/container/'configuration.sha256').read_text().split()[0]
    lines += [f'### {label}', '', f'- XCLBIN：`{server}/{container}/{kind}.xclbin`',
              f'- SHA256：`{digest}`', f'- 源 bitstream：`{server}/{recovery}/build/link/int/partial.bit`',
              f'- 源 routed DCP：`{server}/{prefix}_platform_20260913_02/physical/routed.dcp`',
              f'- [容器元数据检查]({container}/container_metadata_validation.json)', '']
lines += ['XCLBIN 中的 bitstream 已提取并与源文件逐字节比较。运行时 memory/IP/connectivity/clock/partition/embedded/build 元数据已封装并检查；仅省略非运行时必需的 IDE SYSTEM_METADATA 展示图，避免保留实现前的旧地址信息。所有 DCP、bitstream 和 XCLBIN 均留在 eda070。', '',
          '没有开发板，未进行实际加载、PCIe/DDR 运行或网络推理验证。先前单 SLR 基线和失败尝试均保留。恢复过程与命令见 [实验记录](../docs/experiments/platform-recovery-20260913.md)。', '']
(reports/'recovery_summary_zh.md').write_text('\n'.join(lines))
for label, prefix, recovery, container, data, totals in results:
    (reports/recovery/'summary.md').write_text(
        f'# {label} routed-checkpoint recovery\n\n'
        f'Current acceptance: **{data["status"]}**. See [complete results](../recovery_summary_zh.md) and platform_validation.json.\n\n'
        'Native bitstream generation succeeded. The raw v++ recovery exited 1 at rtdgen because the fresh reuse directory lacked address_map.xml; that failure remains recorded. '
        f'The generated bitstream was successfully packaged in {container} using the same-source corrected address map and native cf2sw/xclbinutil commands. '
        'First and second physical audit outcomes, unchanged checkpoint hashes, resource comparisons, timing coverage and remaining review findings are recorded separately. '
        'Legacy REF_NAME DSP/BRAM leaf counters are not physical resource totals; native utilization is authoritative.\n\n'
        f'Server directory: {server}/{recovery}\nSource DCP: {server}/{prefix}_platform_20260913_02/physical/routed.dcp\n')
    (reports/container/'summary.md').write_text(
        f'# {label} recovered XCLBIN\n\n'
        'Container generation and metadata/payload checks: **PASS**. This is not board execution or full timing signoff. '
        f'See [complete results](../recovery_summary_zh.md), container_metadata_validation.json and configuration_info.txt. '
        'The optional IDE SYSTEM_METADATA diagram is omitted; all runtime sections are retained.\n\n'
        f'Server directory: {server}/{container}\nPhysical verification: {recovery}\n')
print('Wrote reports/recovery_summary_zh.md and accelerator_resources_by_slr.tsv')
