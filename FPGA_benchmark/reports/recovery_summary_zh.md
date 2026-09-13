# U250 检查点恢复、产物与独立验证

资源以 Vivado 原生按核、按 SLR 的 utilization 表为准，不含平台 shell。VTA64 为单个 64×64 引擎；CNNA6 为六个独立引擎的多核扩展。布局约束指定 SLR2/SLR3。

| Case | 当前验收状态 | XCLBIN 容器检查 |
|---|---|---|
| VTA64 | REVIEW_REQUIRED | PASS |
| CNNA6 | REVIEW_REQUIRED | PASS |

REVIEW_REQUIRED 表示产物、布线、重开一致性及数值时序检查已通过，但约束覆盖、CDC 和 methodology 告警尚需审查；不等于最终验收通过。PENDING_OR_FAILED 表示证据尚未齐全或有检查未通过。

## 加速器实际资源

| Case | SLR | LUT | FF | BRAM36 等效 | DSP | URAM |
|---|---|---:|---:|---:|---:|---:|
| VTA64 | SLR2 | 43068 | 24645 | 596 | 1803 | 0 |
| VTA64 | SLR3 | 33923 | 3731 | 643 | 2304 | 0 |
| CNNA6 | SLR2 | 138110 | 276620 | 469.5 | 1215 | 0 |
| CNNA6 | SLR3 | 138090 | 276621 | 469.5 | 1215 | 0 |

各核明细见 [TSV](accelerator_resources_by_slr.tsv)。早期 accelerator_regions.tsv 中基于 REF_NAME 的 DSP/RAM 列会漏计展开的原语，不能用于资源总量；仅使用其 primitive_count 验证位置。原始报告保留以追踪这一统计问题。

## 布线与跨 SLR 连接

| Case | 已布线 / 可布线 nets | 路由错误 | 全平台 SLL 使用量 |
|---|---:|---:|---:|
| VTA64 | 525305 / 525305 | 0 | 11315 |
| CNNA6 | 1170278 / 1170278 | 0 | 7870 |

此处 SLL 为全平台统计，包含 shell 和接口跨 SLR 连接；不等同于计算核内部跨 SLR 数量。方向性连接矩阵见各 physical/slr_utilization.rpt。

## 全平台时序

| Case | 内核数据时钟 | WNS (ns) | WHS (ns) | WPWS (ns) | TNS / THS / TPWS (ns) | Setup / Hold / 脉宽失败端点 |
|---|---:|---:|---:|---:|---|---|
| VTA64 | 100 MHz | +0.013 | +0.010 | 0.000 | 0 / 0 / 0 | 0 / 0 / 0 |
| CNNA6 | 100 MHz | +0.057 | +0.008 | 0.000 | 0 / 0 / 0 | 0 / 0 / 0 |

这些是多时钟完整平台的最差裕量，不能用来直接换算计算核 Fmax。完整 min/max/pulse-width 汇总和端点总数保存在每个 platform_validation.json 中。

## 剩余审查与验证证据

- **VTA64**：内部未约束端点 0；未设置 input/output delay 的端口分别为 10/9。
  [机器检查结果](vta64_recovery_20260913_01/platform_validation.json)；未通过或待审项：cdc_no_unreviewed_critical_paths, root_timing_coverage_clean, root_methodology_no_unreviewed_warnings, reopen_timing_coverage_clean, reopen_methodology_no_unreviewed_warnings.
- **CNNA6**：内部未约束端点 0；未设置 input/output delay 的端口分别为 10/10。
  [机器检查结果](cnna6_recovery_20260913_01/platform_validation.json)；未通过或待审项：cdc_no_unreviewed_critical_paths, root_timing_coverage_clean, root_methodology_no_unreviewed_warnings, reopen_timing_coverage_clean, reopen_methodology_no_unreviewed_warnings.

边界端口涉及平台 PERST、DDR reset、QSFP、UART 和管理接口。methodology/CDC 涉及平台时钟定义、时钟门控、PCIe、JTAG 等；未添加一刀切 false path，也未自动豁免这些发现。详细 CDC 报告保留端点与 waiver 标识。

## 服务器产物与来源

### VTA64

- XCLBIN：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/vta64_container_20260913_01/vta64.xclbin`
- SHA256：`ce3050120d6c9ae32e22d3523af96405769f80a5fbb81a529f0cd2307fcfd1e5`
- 源 bitstream：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/vta64_recovery_20260913_01/build/link/int/partial.bit`
- 源 routed DCP：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/vta64_platform_20260913_02/physical/routed.dcp`
- [容器元数据检查](vta64_container_20260913_01/container_metadata_validation.json)

### CNNA6

- XCLBIN：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/cnna6_container_20260913_01/cnna.xclbin`
- SHA256：`4000ce4d441be39518f79bf3d185a9d9835475ead39fb154d8b784c36575c768`
- 源 bitstream：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/cnna6_recovery_20260913_01/build/link/int/partial.bit`
- 源 routed DCP：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/cnna6_platform_20260913_02/physical/routed.dcp`
- [容器元数据检查](cnna6_container_20260913_01/container_metadata_validation.json)

XCLBIN 中的 bitstream 已提取并与源文件逐字节比较。运行时 memory/IP/connectivity/clock/partition/embedded/build 元数据已封装并检查；仅省略非运行时必需的 IDE SYSTEM_METADATA 展示图，避免保留实现前的旧地址信息。所有 DCP、bitstream 和 XCLBIN 均留在 eda070。

没有开发板，未进行实际加载、PCIe/DDR 运行或网络推理验证。先前单 SLR 基线和失败尝试均保留。恢复过程与命令见 [实验记录](../docs/experiments/platform-recovery-20260913.md)。
