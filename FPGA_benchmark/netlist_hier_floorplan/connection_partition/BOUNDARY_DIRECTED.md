# 有向空间距离与边界简化统一

2026-09-26，默认 `directed_distance_model=boundary_directed_v1`。没有配置此字段的历史方案继续使用 `raw_sink_pin_v1`，两者不能混用评分缓存。

## 保留什么

与 `D_hyper` 共用 `boundary_hyper.lift` 的同一次边界提取：

- 同模块 FF→LUT→FF 不计空间距离。
- 同模块 DSP/BRAM/URAM 出发，可越过本模块内部 FF/LUT，到第一个硬资源端点停止；保留不同端点，不穿透 DSP/RAM。它是空间关联，可能跨周期，不是时序路径。
- 跨模块段保留其 FF/宏边界，不跨模块穿透 FF。
- 某模块在当前段内有边界锚点，就省去该模块内部组合 cell 的独立位置。若仅有组合逻辑，则保留一个确定的 LUT 容量加权期望位置。无关寄存器不能吸收该段的代理。
- RAM/LUTRAM/SRL 等边界区别、专用原子、SCC 闭包、未知端口和缓存预算沿用既有规则。

## 有向距离

每条保留的源 bit-net 建立一个以源为中心的有向连接集合：源→每个不同接收锚点，以及源→每个独立组合模块代理。

`D_dir = Σ_e w_e Σ_(v in retained_receivers(e)) E[|X_s−X_v| + |Y_s−Y_v| + γ|SLR_s−SLR_v|]`。

同一源经不同组合分支重汇合到同一原子时只计一次。不同接收原子、不同源 bit-net 仍分别计数。相同资源/模块槽中的两个不同硬资源原子仍有期望距离，不能把相同槽误当成同一个 cell。

组合代理只增加源到该代表位置的空间距离，不宣称恢复其经过顺序或真实路由；顺序和往返风险由原始图上的单周期累计项处理。无边界来源的组合根使用其模块期望位置；没有位置的顶层端口不虚构坐标，相关根不计有向距离并记录。

硬资源/FF 锚点使用容量概率；组合代理为确定的期望坐标，可为非整数。矩阵 CDF 按实际坐标间隔积分，独立验证用所有支撑点对枚举，不进行整数舍入。

## 明确保留的原始图成本

- 分支平方项仍对原始 source→sink-pin 的 SLR 距离收费，系数 32。
- 单周期累计路径项仍在原始 FF/组合图上计算，base=2、weight=128。
- 不增加 Nmax 硬门槛。4 次跨界是否被接受由指数软成本参与权衡；本次未调高指数底数/权重。
- `D_hyper`、partition 的 C+L、资源上限和软扩展规则保持。

因此 `directed_x/y/slr/distance/internal_distance` 是新的空间口径；`raw_boundary_histogram/raw_far_pins/raw_branch_boundaries` 仍是原始引脚口径，两者不应互相推导。保留的“端点分支数”也不是原始 sink-pin 数量或 STA 路径数。

## 接入与验证

`structure_floorplan` 生成新距离缓存；`DirectedModel` 组合新距离和旧分支风险；主评分、坐标调整、交换、退火、最终排序均通过同一评分接口。MIP 起点的距离均值也使用新角色，分支平方代理仍使用原始角色。

`floorplan_cached --graph ...` 可在新目录迁移历史缓存，要求原图 SHA、完整 leaf 身份/归属及物理原子一致。旧 pair 表不能推导新边界；缺失原图时明确失败。新缓存绑定原图、成员和模块顺序。`fixed11_verify` 独立核对新距离，路径/资源核验不变。

旧的 `chain_regions.BranchCost` 是改变成员的链级辅助求解器，它不能复用固定成员下的边界缓存。若传入新规则，明确拒绝，避免悄悄使用旧距离。历史明确使用旧规则的链引导/控制修整仍可回放；本轮支持的是当前固定成员主 floorplan 流程。

固定布局复算，不运行搜索或 P&R：

```sh
python boundary_directed_rescore.py --run /absolute/floorplan \
  --graph /absolute/graph.pkl --output /absolute/new_audit
```

复算输出比较、空间缓存和输入 SHA，不生成新 implementation_input，不能将其当成重新优化的 floorplan。
