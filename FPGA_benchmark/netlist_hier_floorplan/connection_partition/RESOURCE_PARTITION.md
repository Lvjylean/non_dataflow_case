# 资源约束下的连接与逻辑划分（2026-09-24）

模式 `resource_logic_v1`：partition 只决定完整 leaf 成员，不计算位置、D、SLR 距离或模块数量惩罚。历史实验及其配置不改写。9/24 的 GETRF 原生 KaHyPar 对照为 9 模块（C=5918、L=137）；9/25 启用自动联合链保护后，完整验证选出 10 模块（C=4668.75、L=85），256 条链全部完整。当前版本和验证范围见 [RELEASE_9_25.md](RELEASE_9_25.md)，自动保护规则见 [JOINT_UNITS.md](JOINT_UNITS.md)。新 10 模块尚未做 floorplan 或时序验证。

## 目标与约束

\[
J_P=\alpha C+\beta L,\quad \alpha=\beta=1
\]

\[
C=\sum_e w_e(\lambda_e-1),\qquad
L=\sum_h\omega_h(\lambda_h-1)
\]

`C` 用原网表超边：每个 bit-net 的不同物理原子组成端点，数据权重 1、控制权重 0.25；`λ` 是涉及的模块数。`L` 沿用已有逻辑核心集合与软超边，`core_soft_strength=0.1`，权重保留原四分之一单位取整规则。算子预收缩只生成提案，最终 C/L 均在原图上重算。

对模块 m 的九维需求向量 q，要求存在**同一个匿名 die 容量向量**满足：

\[
\exists s,\ \forall r:\quad q_{m,r}\le\lfloor\rho_r C_{s,r}\rfloor,
\qquad \rho_{URAM}=1,\quad\rho_{其他}=0.7.
\]

不能把某个 die 的 DSP 最大值与另一个 die 的 RAM 最大值拼成虚构容量。这里的 s 只用于“至少能装进一类 die”的资源检查，不是选中的落点，也没有证明所有模块可以同时放下。

仅从设备表读取资源数量和 die 分组，不读取 x/y。平均可用 CR 资源与等效粒度：

\[
\bar U_r={\rho_r\sum_s C_{s,r}\over N_{CR}},\qquad
a_m=\max_r{q_{m,r}\over\bar U_r}.
\]

这不是实际矩形面积；异构资源集中于某些列，实际所需范围须在后续 floorplan 中确定。若某类资源容量为 0，有需求时等效粒度为无穷大且硬约束不通过；无需求时该维为 0。

**1 CR 是软下限**：a<1 时优先检查合并，不要求每种资源都达到一份 CR 容量。没有连接、连接弱或合并后超过资源上限，都允许保留小块。允许模块大小和资源配比明显不同。

目前 U250 表的单模块主要硬上限：LUT 302400、FF 604800、DSP 2150、BRAM18 940、URAM 320；其余为 LUTMEM 138432、CARRY8 37800、MUXF7 151200、MUXF8 75600。

## 求解流程

1. 复用 post-opt 图、连接缓存及逻辑核心。保留验证过的完整算子预收缩。若一个可选算子整体超过单 die 预算，则撤销该算子的预收缩；若不可拆的物理原子本身超预算，明确失败。
2. 用 KaHyPar 递归二分，分别从 1/2 个等效 CR 的初始粒度生成候选，seed=0/1。原生 KaHyPar 使用一个当前超限最严重的资源作为标量权重；每个子块都重新检查完整资源向量，标量平衡不充当资源可行性证明。
3. 展开到原图，验证真实 cut/km1 等价。初始粒度只是搜索起点；撤销旧固定初始 k 和 150000 cell 上限。
4. 沿用选择性合并门槛：两模块共享超边权重 / 两者较小的 incident 权重 ≥0.02，且合并后满足资源预算。优先处理不足 1 CR 的模块，不强迫弱耦合模块凑规模。
5. 保留合并历史及原有对照。进行完整算子/内部连通分量局部移动，接受原有非增 km1、非增加权跨模块 pin、算子完整性条件，并改为检查全部九类单 die 资源。局部移动不直接优化 L，因此保留移动前后候选，最后以 C+L 选择。
6. 沿用相对于固定 baseline 的新增连接预算：全局 0.025W、局部 0.1 incident-weight。资源限制和连接预算必须同时满足；无候选时报告冲突，不偷偷放宽预算。
7. 精确按 J=C+L 排序，之后依次以 C、L、候选名称打破同分；删除 D、0.0025Wk 和“1% 内优先更少模块”规则。两项同时由 2 改为 1，不改变相对权重、逻辑软超边提案或候选排序。模块数只作为结果统计。
8. 导出所有 leaf 的成员归属、资源表、模块间连接和来源信息。独立小模块仍参与资源与完整成员导出，不因没有外连而消失。
9. **冻结 partition 后**才在 floorplan 阶段生成区域。把原有静态区域初始化/局部打磨移到此阶段，随后仍使用原有 fixed11_search/explore/verify。保留 boundary_spatial_v1、方向成本、平方惩罚、资源比例和软扩展规则，搜索器未替换。

仅 C+L 的数学最小化天然倾向合并。0.02 亲和度门槛、资源硬上限与从细到粗的有限候选流程共同限制合并；这不是 C+L 的全局最优算法，也不能保证模块数落在某个指定区间。门槛是沿用的工程选择，须用实际 case 验证。

## 配置与入口

- `balanced_config.json`：启用模式、C/L 权重；物理字段只为历史兼容和 floorplan 初始化保留，在新 partition 中不调用。
- `resource_partition_config.json`：70%/100%、1 CR 软下限、初始粒度、亲和度门槛。
- `structure_config.json`：算子验证、seed、局部调整预算。旧 bootstrap_k/bootstrap_cell_cap/max_region_candidates 在新模式中不参与决策。

在具备原生 KaHyPar、NumPy 和后端依赖的实验机中，仅生成 partition：

```sh
python3 structure_pipeline.py partition /absolute/new_run \
  --from-run /absolute/original_cache_run \
  --kahypar-python /absolute/kahypar_python \
  --kahypar-path /absolute/kahypar_module_dir
```

`--from-run` 为含 graph.pkl、cr.tsv、baseline、balanced、planning_source 的原始缓存实验根。当前 GETRF 对应 `getrf_partition_floorplan_20260923_7VSNOFzw`，不是其 implementation_input 子目录。输出目录须为新的绝对路径。

之后独立执行 `python3 structure_pipeline.py floorplan /absolute/new_run`；`run` 动作则依次执行 partition 与 floorplan，均不运行 Vivado placement/route。旧 `balanced_pipeline.py` 不支持新模式，会明确拒绝，避免误用旧物理排名。

partition 的 `balanced/selected/` 不包含 `static_regions.json`。区域只写到 `floorplan/input/export/`，不回写所选模块。历史冻结配置缺少新模式标记时继续使用旧流程。

## 验证范围

2026-09-25 起，当前资源划分入口默认启用自动存储—计算联合链发现与全流程保护。
详见 [JOINT_UNITS.md](JOINT_UNITS.md)：完整联合链先收缩，再参与 KaHyPar；
展开、局部调整、历史候选准入、排名、导出以及 floorplan 输入均检查完整性。
`J=C+L`、资源上限、通信预算和默认 seed/初始粒度不变。

本地测试覆盖匿名 die 的共同向量约束、坐标置换不变性、硬上限、资源偏科、弱连接小块例外、递归标量提案后的多维复核、局部移动预算、D/k 无关评分、完整孤立 leaf 导出、partition 到 floorplan 的阶段隔离与原有回归检查。

小图递归测试用穷举二分作独立提案源；floorplan 初始化测试替代原生 MIP，仅验证真实物理评分、资源审计、ID 转换和阶段衔接。另有完整 GETRF 原生 KaHyPar 运行与原图独立重算证据；没有完整新 Gurobi/floorplan 或物理实现质量验证。
