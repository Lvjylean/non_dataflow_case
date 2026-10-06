# 2026-10-06：单周期累计跨 die 惩罚与 FF、输入联合优化

发布分支：`partition-floorplan-10_6_惩罚单周期累计跨die_ff与输入联合优化`。

本次从已发布的 9 月 25 日版本 `887ca564b1f679c840b1c4f417665cbaa4d3dbac` 建立独立分支，保存当前 partition、floorplan 和物理后端的源码、配置、测试与说明。Partition 的选择目标仍为 **C+L**；物理区域和累计跨 die 惩罚属于后续 floorplan 成本。物理后端采用当前 `backend_broadcast_scope_repair100` 快照，保留其完整内部依赖，不依赖其他未发布的历史 backend 副本。

## 主要改动

|方向|主要实现|解决的问题|源码与说明|
|---|---|---|---|
|Partition|自动识别有向局部逻辑锥，支持整组联合移动；复用候选缓存继续细化，目标仍为 C+L|单个 cell 调整难以保持数据、选择和控制逻辑的关联|[DIRECTED_UNITS.md](connection_partition/DIRECTED_UNITS.md)、`directed_units.py`、`directed_cached_refine.py`、`mux_cone_refine.py`|
|Floorplan 成本|统一边界有向距离模型；增加单周期路径累计跨 SLR 指数惩罚|识别 A→B→A 等往返，而不只比较起点与终点|[BOUNDARY_DIRECTED.md](connection_partition/BOUNDARY_DIRECTED.md)、[CUMULATIVE_PATH_FLOORPLAN.md](connection_partition/CUMULATIVE_PATH_FLOORPLAN.md)、`cumulative_paths.py`|
|RAM/DSP 路径覆盖|读取原生 RAM/DSP 内部时序弧及寄存器配置，构建 `macro_timing_v2`|修复只按普通 FF 建图时遗漏宏单元路径的问题|`macro_timing_extract.tcl`、`macro_timing.py`、`path_cache.py`|
|广播候选识别|穿透恒等 LUT1 分发树找回原始广播 FF；识别同 SLR 起止、组合逻辑绕到另一 SLR 的情况|避免插入分发树后漏识别原始高 fanout 信号|`code/regional/broadcast_components.py`、`locality_plan.py`、`cone_locality.py`、`locality_inventory.tcl`（后端目录内）|
|FF 与输入联合优化|联合评估 FF、必要 D 输入 LUT/MUX、CE 等控制输入；支持完整数据和选择支路复制|防止复制 FF 后，上游跨 die 变成新的关键路径|`code/regional/joint_input.py`、`joint_input.tcl`、`joint_gate.py`、`run_case.py`|
|物理合法化|改接 D 输入后清理旧路由、释放相关 FF 和共享站点；核对副本实际 SLR，支持有界局部修复|防止非法打包，以及副本虽绑定区域却实际越界|`physical_eco.tcl`、`code/regional/local_broadcast.tcl`、`locality_plan.py`、`audit.tcl`|
|编译提速|批量读取端点 setup/hold、数组化序列化、阶段内保护属性和 Pblock 成员缓存、减少重复打开与中间输出|减少逐对象调用和重复检查，保留完整验收|`code/regional/timing_fast.tcl`、`locality_inventory.tcl`、`local_broadcast.tcl`、`chain.tcl`、`checkpoint_io.tcl`|
|恢复与调度|验证 checkpoint、源码、输入和计划身份后恢复；按阶段内存预算并行准入|复用有效 placement，避免重复编译与超额内存准入|`run_case.py`、`code/regional/recovery.tcl`；[阶段调度适用范围](phase_memory_scheduler/PUBLICATION_SCOPE.md)|

上述 Python/Tcl 文件未注明目录时，partition/floorplan 文件位于 `connection_partition/`，物理后端文件位于 `backend_broadcast_scope_repair100/`。9 月 25 日分支主要发布 partition/floorplan；本次首次在同一发布分支收录完整后端，因此不能把后端中的全部历史功能都称为 9 月 25 日以后新增。

## Partition 与 floorplan 的含义

保留资源约束、完整算子和自动发现的计算链保护。有向逻辑锥是可联合移动的候选，不是强制把整张网表合并为大模块。缓存绑定原图、成员及配置；完整网表和 native Vivado 提取在服务器完成。

累计惩罚对每个受支持的捕获单元取最大单周期结构路径计数：

```text
Nmax(t) = max over launch→capture paths p:
          Σ abs(SLR(u) - SLR(v))
P = weight × Σt (base ^ max(Nmax(t)-1, 0) - 1)
J_floorplan = existing J_floorplan + P
```

当前默认 `weight=128`、`base=2`，累计跨边界次数 0/1/2/3/4 对应新增惩罚 0/0/128/384/896。寄存器边界结束当前周期；并行与重汇合分支取最大值，不把无关路径相加。A→B→A 的计数为 2。SLR0→SLR2 一段跨两个相邻边界，也计 2。移动未改变 SLR 时复用分数；改变 SLR 时增量传播，超出工作阈值退回完整计算而不截断路径。

`macro_timing_v2` 纳入 RAM/DSP 的原生有效弧、内部寄存器与组合旁路。普通 LUT/CARRY/MUX 使用保守结构关系；未支持的宏显式报告。它仍是结构成本模型：不等价于完整 STA，不自动过滤所有时钟域、false/multicycle path 或逻辑敏化条件，也不保证最终实际跨 die 次数或 WNS。

当前累计模型要求每个物理模块的 **core 位于单个 SLR**；软扩展不改变 core 成本。需要多 SLR core 的模块必须增加内部位置模型，不能直接以中心点猜测路径次数。搜索包括 MIP 初始解、局部细化和退火；MIP 是代理初始化器，不是完整非线性目标的全局最优证书。历史配置缺失新字段时按文档保留旧模型，缓存不能跨不同模型直接混用。

## 当前物理后端流程

入口为 [run_case.py](backend_broadcast_scope_repair100/run_case.py)，普通信号验收目标严格小于 100，内部构树目标 96。时钟、常量等按显式类型排除，不以实例名筛选广播。保留三次常规 placement、一次完整 routing 和最终独立重开；条件时序回退及局部合法化可能增加 placement。本次未合并第二、第三次 placement。

```text
干净 post-opt + 验证过的 floorplan 输入
  → 第一次 placement：取得初始物理位置
  → 基础分发树 ECO、区域与保护处理
  → 第二次 placement
  → 完整结构采集、广播/绕路识别、FF 与 D/CE 输入联合规划
  → ECO、旧路由清理、共享站点释放
  → 第三次 placement、实际 SLR/物理/结构/时序检查
  → 必要的有界修复或候选回退
  → 一次完整 route_design
  → 布线、fanout、结构、区域与时序验收
  → 独立进程重开最终 DCP，重复最终验收
```

FF 的新位置同时考虑目标 SLR 的接收端、完整 D 输入数据/选择支路、CE/R/S 及上游共享 fanout。复制候选必须通过输入余量、资源和支持范围检查；仅把 FF 挪到另一 die 并不自动安全。原始保护和恒等树层级别名在修改前验证解锁范围，改接后验证连接并恢复保护。新增分发节点解除永久精确 LOC/BEL 固定，保留算法要求的 SLR/区域归属；必要局部修复使用临时位置固定，成功后释放。

默认布局时序策略为 `nonworse`；`positive` 仅在显式选择时允许全局 WNS 有所下降但仍为正，其他端点、TNS、hold、结构和物理检查继续执行。布局预测通过不意味着 routed WNS 必然为正。未知结构、时钟/时序例外或不完整输入锥不能靠跳过检查放行。

## 加速、恢复与可选能力

批量读取端点 pin setup/hold，非有限值使用原路径提取回退；同一 DCP 上逐端点及判定等价性已有验证。保护属性与 Pblock 缓存限制在不变的阶段内，ECO 后重新采集。单会话串接 seed/base/generic 减少重复打开，中间输出仍保留必要恢复边界。`checkpoint_io.tcl` 写 DCP 时临时降低线程数并恢复原配置，是稳定性措施，不能视作通用崩溃根因修复。

跨会话静态 discovery 缓存代码与测试一并保存，但当前证据中的 `native_static_discovery_cache_pass=false`，本次运行未启用该复用。它需要同基准、源码、参数和排除集合的原生等价性证明后才可准入，不能与阶段内数组/缓存提速混为一谈。

恢复只接受受支持的 checkpoint 边界，验证完整源码清单、输入字节、周期、floorplan 和计划身份。不重放失败后已部分改接的网表。耗时应分列工具阶段、检查、恢复、内存等待与总墙钟；复用前两次 placement 的恢复耗时不能当作完整编译耗时。

另外保存以下可选能力；**它们并非全部在当前 affinity02 实验启用**：

|可选能力|作用与范围|说明|
|---|---|---|
|大模块内部完整计算链区域引导|在 parent 范围内划分完整链物理组，保留逻辑 partition|[CHAIN_GUIDANCE.md](connection_partition/CHAIN_GUIDANCE.md)|
|URAM 专属软范围|扩大 URAM 的位置软范围，保持 core 资源记账，不产生额外容量|`uram_soft_export.py`、`uram_resource_adapter.tcl`|
|控制路径局部修整|使用验证过的路径做有界区域调整，不加流水级|[CONTROL_PATH_REFINEMENT.md](connection_partition/CONTROL_PATH_REFINEMENT.md)|
|SLL bundle 临时占位|U250 对每个边界 bundle 单独判断热点；当前实验方案阈值 80%、占位 1/3；全部布局结束后、完整 routing 前移除|`plan_sll.py`、`sll_balance.tcl`；需要对应 native 占位/移除验证|
|阶段内存调度|使用尚未驻留的阶段预算加余量准入，等待/暂停进程的 RSS 仍计入占用|`phase_memory_scheduler/`；GETRF 两组适配器，非任意作业通用队列|

SLL 占位使用临时对象，不给真实数据路径增加流水级。SLL 物理映射和容量是器件相关的，不应直接套用到其他器件。当前 affinity02 没有启用 SLL 占位。

## 使用与验证边界

详见 [partition/floorplan 入口](connection_partition/README.md) 与 [后端入口及原生测试](backend_broadcast_scope_repair100/README.md)。Python 需要 NumPy；完整 partition 另需匹配的 KaHyPar 环境，MIP 初始解需 Gurobi 及有效许可。Tcl 模拟测试使用 `tclsh`；native 集成需 Vivado、目标器件支持和服务器环境。

```sh
# Synthetic/source regression only; no full-netlist or native Vivado work locally.
python3 -m unittest discover -s connection_partition -p 'test_*.py'
python3 backend_broadcast_scope_repair100/validate_local.py /tmp/backend-release-validation
python3 phase_memory_scheduler/test_scheduler.py

# Native backend invocation: use verified external experiment inputs and proof.
python3 backend_broadcast_scope_repair100/run_case.py \
  --input /absolute/path/post_opt.dcp --expected-sha256 CHECKPOINT_SHA256 \
  --floorplan /absolute/path/implementation_input --period PERIOD_NS \
  --work-root /absolute/path/new_run --validation-json /absolute/path/native_validation.json \
  --vivado /absolute/path/vivado --broadcast-locality
```

`validate_local.py` 的模拟测试结果不能代替 `--validation-json` 所需的原生证明。启用广播局部性需原生 implementation 与独立重开、完整源码 hash 匹配；SLL、scope recovery 等另有各自准入条件。原生证据及 DCP 留在服务器，不在 Git 中伪造可移植 PASS 文件。

本次发布核对后端全部 153 文件与当前实验冻结源码、原生验证清单逐项一致。已有 native integration、FF/MUX 联合优化、pin slack 等价性、物理 ECO、广播局部性与范围修复证明通过；这不是对任何新输入均可时序收敛的承诺。发布验收记录见 [RELEASE_10_6_VALIDATION.md](RELEASE_10_6_VALIDATION.md)，源码清单见 `release_10_6_manifest.json`。

本分支不包含 DCP、位流、设计派生的 membership/netlist/连接缓存、实验计划或大型日志。历史实验与正在运行的实验不修改、不重启。当前发布范围没有新做前端、加流水级或改变算法吞吐量。
