# 独立的区域扇出加速流程

入口：[run_case.py](run_case.py)。这是修复后的 `regional_fanout_eco` 的完整独立副本，
不用导入原目录；原公共版本和用户提供的 fixed 版本均保留原样。
来源见 [fast_origin_manifest.json](fast_origin_manifest.json)，验证见
[加速整合报告](../../reports/regional_fanout_fast_code_20260922_01/加速整合说明.md)。

## 已接入的优化

1. **FF/CE 批量重接。** 按每个端点实际连接的局部网段分组，同网段使用原生 pin
   对象批量断开，按 net/pin 对批量连接，默认每批上限 2048。使用修复后的
   `tracking_key` 将所有 removed 记录归到原始叶驱动对应的网络；一次合并写回
   每组 tracking 记录。多网络连接按对象 NAME 映射，不能依赖查询返回顺序。
2. **区域 LUT 批处理。** 每根 root 的连接入队，在保护恢复和完整连接检查前
   刷新；相同区域的 Pblock 成员按 512 个一批绑定。区域 Pblock 仍是原计划
   精确范围、硬约束且非排他，EXCLUDE_PLACEMENT 在 IS_SOFT 之前写入。
   失败路径丢弃队列、恢复原保护后终止，不继续使用部分修改设计。
3. **复用已验收恢复 DCP。** 继承专用错误码和每边界一次的新进程恢复。
   post-place/post-route 重开后，先执行全部原结构、真值、保护、位置和区域
   检查，再将该 DCP 复制为正式检查点。期间没有设计修改，不再次序列化。
   不使用硬链接；Python 核对正式文件 SHA256 与诊断文件记录完全相同。
   普通无故障路径仍正常保存检查点，最终独立重开和时序比较保留。

FF/CE 候选识别、RAM-fed FF 支持、本地 CE、LUT 树拓扑与默认阈值不变。
区域树 branch limit 仍为 96；不能将此局部约束当成全设计 fanout<100 证明。
同一 Vivado 设计内的 ECO/placement/routing 仍按依赖串行执行；批量操作不等于
同时修改同一设计。该阶段一次 placement、一次完整 route，上游 seed/base
的物理步骤不由本入口合并或省略。

## 使用和对照

```sh
python3 /absolute/path/regional_fanout_eco_fast/run_case.py \
  --input /absolute/path/pre_route.dcp \
  --expected-sha256 INPUT_SHA256 \
  --work-root /absolute/path/new_fast_run \
  --input-stage placed --execution-profile fast
```

`--execution-profile fast` 是默认值；在另一全新目录以 `reference` 运行，可以
使用同样修复、同样策略的原执行顺序做对照，关闭批处理和检查点复用。
两个版本须从同一个输入分别运行，不能在同一个 DCP 上重复应用 ECO。
原有 `--mode run/inspect/edit/place/route`、`--regional off`、`--legacy-eco skip`
继续支持。place/route 模式仍要求 plan、输入 SHA256 和 baseline-dir。

本入口处理已完成上游基础树处理的 placed/pre-route DCP，不自动运行综合、
opt_design、floorplan、seed/base，不依赖任何 TRTRS cell 名或实验目录。
全部原生运行在服务器的新目录进行。

## 性能证据和边界

- `execution_<mode>.tsv`：该 Vivado 进程内各操作调用次数和微秒耗时，含对象
  查询、native disconnect/connect、Pblock 绑定、正式保存和检查点复制。
- `regional_runtime.tsv`：逐 root 原有阶段计时，便于与 reference 对照。
- `status.json`：阶段耗时、恢复状态以及 `checkpoint_publications` 的 SHA256
  验收；模式返回码 75 是有限次数的恢复交接，不是对任意错误的重试。
- `implementation/recovery/*_published.tsv`：已验收检查点复用来源。

小型原生层级探测确认，跨局部网段使用单个顶层 net 批量断开不能保证正确：
Vivado 可以只给 warning 而保持端点连接。此方案没有启用。
上游基础树的数万次跨网段断线调用仍待更深入的边界变换研究，不能把扩大批次
算成消除全部调用的收益。

原完整实验的重复 `report_utilization -slr` 来自外层审计与本阶段的组合；本独立
入口内没有那一对重复调用。本次不引入外层审计依赖、不省略独立重开报告，
因此报告去重暂未计入收益。完整 TRTRS 的编译时间和 WNS 变化须单独实验确认。

## 验证

本地执行全部 `test_*.tcl` 和 `python3 -B -m unittest -v test_recovery`。
测试覆盖别名提升、打乱原生对象返回顺序、未知信号/重复端点拒绝、队列清空、
断线/连接批次上限、验收前禁止发布，以及正式检查点字节篡改拒绝。
小型服务器 A/B、完整叶级图与约束比较、两处故障恢复记录见上述报告。
