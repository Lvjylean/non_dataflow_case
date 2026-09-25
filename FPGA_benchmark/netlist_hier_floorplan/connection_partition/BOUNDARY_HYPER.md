# 按模块边界与硬资源锚点计算 D_hyper

版本：`boundary_spatial_v1`；用户于 2026-09-24 确认两端均为 DSP/BRAM/URAM 即计入，模块内部允许跨过连续 FF/LUT，到第一个 DSP/RAM 停止。只修改 D_hyper，D_dir、分支平方项、资源约束、KaHyPar、局部调整与 floorplan 求解策略均未修改。

## 建图规则

1. 使用原始 cell/net 缓存及当前模块标签，不使用算子收缩后的图。专用级联原子保持完整。
2. 从 FF、DSP、BRAM、URAM 等边界的每条输出 bit-net 出发，沿组合逻辑传播到下一批边界。每个源 bit-net 形成一个扇出超边；重汇合只保留不同端点，不枚举和累计所有路径。
3. 若该段涉及多个模块：保留所有已遇到的边界端点。同一超边在某模块有边界端点时，不再为该模块中的组合 LUT 增加独立随机位置；若没有边界端点，则保留一个组合逻辑位置代理。判断依据是这条超边，不是模块内是否存在无关 FF。
4. 若该段在同一模块：只有 DSP/BRAM/URAM 源继续穿过内部 FF/LUT，遇到第一个 DSP/BRAM/URAM 停止。只保留源及可达的不同硬资源端点；少于两个锚点时成本为零。内部遍历不越过模块边界。FF 出发的纯内部段不单独计入。
5. FF/LUT 环先做强连通分量缩并，避免无穷遍历；重汇合不会按路径数放大权重。没有边界来源的纯组合环/孤岛保留原网的跨模块位置代理并计入审计。

“跨过 FF”仅是建立计算—存储空间关联，不修改 FF，也不将其声明为同周期路径。

| 连接及归属 | D_hyper 使用的位置 |
|---|---|
| 同模块 FF→LUT→FF | 不计入 |
| 同模块 RAM→FF→FF→DSP | RAM、DSP |
| 同模块 DSP→LUT→DSP | 两个不同 DSP 原子 |
| 同模块 RAM→DSP→RAM | 分别建立 RAM–DSP 和 DSP–RAM，不穿透 DSP |
| RAM(A)→LUT(A)→FF(B) | RAM(A)、FF(B) |
| RAM(A)→LUT(B)→DSP(C) | RAM(A)、B 的组合位置、DSP(C) |
| FF(A)→LUT(B)→FF(A) | A 内两个 FF、B 的组合位置，不能误判为纯内部 |

## 位置与公式

保留的 FF/DSP/BRAM/URAM 等原子端点仍采用对应资源的容量概率：

`P(X_v=c) = K[c,resource(v)] / sum(K[c',resource(v)] for c' in R[module(v)])`。

不含边界锚点的组合模块代理使用一个确定的期望位置：

`mu_m = sum(K[c,LUT] * (x_c,y_c,SLR_c)) / sum(K[c,LUT])`。

它是几何代表点，跨 SLR 时可能具有非整数 SLR 坐标，并不是新建或实际放置在该坐标的 cell。多个重叠模块具有相同期望位置时，其代理之间距离可以为零；这是粗粒度模型，不是布线保证。

对于上述变换后有效位置集合 A(e)：

`D_hyper = sum_e w_e * E[range_x(A(e)) + range_y(A(e)) + gamma * range_SLR(A(e))]`。

保留原有 gamma：partition 区域评估为 4，当前固定成员 floorplan 为 8。源网数据权重为 1、控制权重为 0.25；中间 LUT 层数、FF 层数及重汇合路径数不会重复累加该源网的权重。不同源 bit-net 仍分别计入。原始 cut/km1 及 W 完全不改为新超边权重。

为了精确处理非整数代理位置，成本在各分布支撑点之间按区间宽度积分 CDF，不把均值向整数 CR 舍入，也不把代理重新当作均匀随机 LUT。

## 接入与缓存

- 本地 `balanced_config.json`、`directed_config.json` 已选择新模型；缺少 `hypernet_model` 的历史配置按 `all_atom_v1` 处理。
- `physical_model.build` 统一创建模型；partition 的区域评分、稳定性分析以及 structure floorplan 准备入口均已接入。
- 新配置不能直接加载旧 `netmodel.pkl`。`floorplan_cached` 在写输出目录之前拒绝版本不匹配；`directed_search` 再核对实际模型对象。
- 新模型的控制组需要按新 D 重新评估，不能把历史旧 D 的 J 混入同一次排名。历史结果与输入文件不改写。
- 当前图缓存有 cell 连接，没有完整引脚时序弧和宏寄存器配置。该模型是保守的连接空间模型，不能证明边界为真实 STA 端点、路径可敏化、时钟关系或关键程度。未定位端口没有虚构位置；SRL/LUTRAM、锁存器保留为边界，不作为普通 FF/LUT 穿透。
- 闭包缓存达到 `boundary_frontier_max_entries` 时显式失败，不截断后输出一个看似完整的结果。当前值为 10,000,000 项，仅用于限制预处理内存。

## 固定布局复算

在存有可信原始大图的服务器上可执行：

```sh
python3 boundary_rescore.py --graph /absolute/graph.pkl \
  --groups /absolute/groups.json --device /absolute/cr.tsv \
  --solution /absolute/floorplan/solution.json --output /absolute/new_cost_comparison
```

该入口不执行搜索。它分别计算旧、新 D_hyper，以独立标量积分复核新值，在旧解成本吻合时给出仅替换 D_hyper 的 J。输入摘要写入结果；输出目录必须新建。用于再次求解的模型缓存应通过原始图和固定成员重新生成，不能重命名旧缓存冒充新模型。

本次只完成本地代码与小图验证，没有重跑 GETRF/TRTRS partition 或 floorplan，没有上传服务器、运行 Vivado 或发布 Git。D_dir 中旧的内部 FF/LUT 随机距离仍保留，所以不能声称整个 J 已消除该偏差。
