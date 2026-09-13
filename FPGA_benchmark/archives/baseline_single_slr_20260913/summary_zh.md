# U250 VTA / CNNA 基线结果

两个完整加速器内核均已完成 U250 OOC routing，并通过独立重新打开检查点复核。全接口 hold 时序尚未收敛，因此这是路由基线，尚未完成上板运行验证。

服务器：eda070。目录：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark`。Vivado 2023.2，器件 `xcu250-figd2104-2L-e`，时钟周期 10 ns，输入/输出延迟 1 ns。

| 指标 | VTA | CNNA |
|---|---:|---:|
| 完整路由网络 | 46,957 / 46,957 | 108,985 / 108,985 |
| ROUTED_FULLY | 1 | 1 |
| 路由错误、缺口、部分路由、冲突 | 全部 0 | 全部 0 |
| 黑盒、最终 DRC error / critical warning | 全部 0 | 全部 0 |
| LUT | 20,113 | 35,746 |
| FF | 19,186 | 72,369 |
| BRAM tile | 136 | 138.5 |
| DSP | 267 | 405 |
| URAM | 0 | 0 |
| 逻辑所在 SLR / SLL 用量 | SLR0 / 0 | SLR0 / 0 |
| 全接口 WNS / WHS（ns） | +1.157 / -2.463 | +4.224 / -2.338 |
| 寄存器间 max / min slack（ns） | +1.157 / +0.009 | +4.224 / +0.009 |
| 实现用时（不含 HLS、复核及审计） | 13:56.75 | 16:15.24 |
| 峰值 RSS（MiB） | 6597.33 | 6613.54 |

独立复核重现了网络数量和时序结果；只读审计前后 DCP SHA256 一致。寄存器间时序通过不代表全接口时序通过，验收器保留 `timing_status=FAIL`。

## 来源与范围

- VTA：完整 fetch/load/compute/store、指令和依赖队列、共享 SRAM。Vitis HLS 2023.2 四模块生成成功，上游 ALU/blocked GEMM C 仿真通过；该仿真不覆盖装配后的 AXI 系统或板卡。
- CNNA：使用锁定上游版本中 Vivado HLS 2019.1 导出的完整 cnn_top HDL。2023.2 源码探测因缺少 systemc.h 失败，尚未完成源码重新生成或新增功能等价验证。
- 两者保留内部并发结构，不能描述为所有模块完全顺序执行。外层增加真实 BUFG，未新增计算流水级。
- VTA BD 构建存在 BRAM MASTER_TYPE 元数据和 AXI lock 宽度适配告警，日志保留；最终 DRC error/critical 为零不代表所有构建告警消失。
- 尚无 PCIe/XRT shell、DDR 控制器、bitstream 或上板推理。默认规模均未跨 SLR，扩大阵列应作为后续独立实验。

## 归档

- [VTA 验证记录](vta_buffered_u250_20260913_04/validation.json)
- [CNNA 验证记录](cnna_buffered_u250_20260913_04/validation.json)
- [维护和复现说明](../README.md)、[实验记录](../docs/runs.md)、[架构说明](../docs/architecture.md)

最终 DCP 仅在服务器上述项目目录中：

```text
runs/vta_buffered_u250_20260913_04/routed.dcp
runs/cnna_buffered_u250_20260913_04/routed.dcp
```

失败及被替代的尝试保留。旧只读 CNNA 审计 PID 2789887 经用户明确授权后终止，检查点未变化。源码哈希清单、实际输入脚本快照、端口映射检查及物理报告均已归档；本地不保存 DCP。
