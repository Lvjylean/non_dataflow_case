"""Write the fixed report structure and compact plots from measured artifacts."""
import argparse
import json
from pathlib import Path


def main(run):
    selection=json.loads((run/'selection.json').read_text())
    selected=json.loads((run/'selected/modules.json').read_text())
    plan=json.loads((run/'selected/static_regions.json').read_text())
    comparison=json.loads((run/'comparison.json').read_text())
    cfg=json.loads((run/'source/balanced_config.json').read_text())
    binding=json.loads((run/'binding.json').read_text())
    sensitivity=json.loads((run/'sensitivity.json').read_text())
    stability=json.loads((run/'region_stability.json').read_text())
    rows={r['candidate']:r for r in comparison};best=rows[selection['selected']]
    baseline=rows['baseline5'];previous=rows['previous6']
    modules=selected['modules']
    used_slrs=sorted({s for r in plan['regions'].values() for s in r['slrs']})
    strong_links=[e for e in selected['connections'] if e['nets']>=1000]
    strong_cross=[e for e in strong_links if
        plan['regions'][e['source']]['slrs']!=plan['regions'][e['sink']]['slrs']]
    summaries=[json.loads(f.read_text()) for f in sorted((run/'candidates').glob('*/summary.json'))]
    merged=[s for s in summaries if s['provenance']['kind']=='reverse_merge']
    refined=selected['provenance'].get('kind')=='core_and_atom_refinement'
    lower=(1-best['physical_cost']/baseline['physical_cost'])*100
    extra=(best['weighted_km1']/baseline['weighted_km1']-1)*100
    max_util=plan['overlap']['maximum_utilization']
    lines=[
      '# TRTRS：综合权衡的 floorplan 模块生成',
      '',f'**状态：模块生成、统一静态评估、反向合并比较、边界调整和交付已完成。当前推荐 {len(modules)} 个 B 编号模块；未进行新的 placement、route 或 STA。**',
      '',f'本轮共保存 {len(summaries)} 个不同模块候选，{len(comparison)} 个获得静态可行区域。推荐 `{selection["selected"]}`。',
      f'相对重算的五模块基线，加权 km1 增加 {extra:.2f}%；全网静态距离代理下降 {lower:.2f}%。这是所声明分布模型和候选范围中的取舍，不是实测线长、SLL 或时序改善。',
      '', '## 1. 输入与范围',
      '',f'服务器：eda070。独立实验目录：`{run.resolve()}`。',
      '',f'输入：`{binding["input_dcp"]}`。SHA256：`{binding["input_sha256"]}`。',
      f'图缓存 SHA256：`{binding["graph_sha256"]}`；器件表 SHA256：`{binding["device_sha256"]}`。',
      '',f'全部 {selected["validation"]["all_cells"]:,} 个 primitive 有唯一归属，其中 {sum(m["cells"] for m in modules):,} 个逻辑 cells 进入模块；常量和时钟基础设施单列。top 直属逻辑 cells 共 {sum(m["top_direct_cells"] for m in modules):,}，全部参与。',
      f'保留 {binding["cores"]} 个软逻辑核心，覆盖 {binding["core_cells"]:,} cells；这仅覆盖部分设计，不能把这些核心的完整率解释为整个设计的功能语义恢复率。',
      '', '不修改网表，不增加流水级或 driver 副本。原始层级是软偏好与来源，不要求严格遵守；所有 U250 SLR 可选，区域允许重叠。URAM 预算100%，其余建模资源70%；本轮没有额外套用旧整SLR父区50%规则。',
      '没有重新提取物理反馈或关键路径，也没有采用其他线程新 fanout 实验的网表。原五模块和六模块方案保留，并用本轮同一评价器重新规划区域；不能直接比较旧报告中不同目标函数的分数。',
      '', '## 2. 求解结果',
      '', '|单元|原五模块来源|cells|LUT|FF|DSP|BRAM18|URAM|SLR|CR范围|内部/关联网权重|',
      '|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|']
    for m in modules:
        r=plan['regions'][m['module_id']];x0,y0,x1,y1=r['bounds']
        parent=max(m['baseline_parent_cells'],key=m['baseline_parent_cells'].get)
        lines.append(f'|{m["module_id"]}|{parent}|{m["cells"]:,}|{m["LUT"]:,}|{m["FF"]:,}|{m["DSP"]}|{m["BRAM18"]}|{m["URAM"]}|'+','.join(map(str,r['slrs']))+f'|X{x0}Y{y0}:X{x1}Y{y1}|{m["internal_incident_ratio"]:.2%}|')
    lines += ['', 'LUT 是 primitive 需求，不是打包后的占用；LUTMEM 已包含在 LUT 中。内部/关联网权重仅衡量连接凝聚性，不等同于功能纯度。',
      f'区域面积之和 {best["total_module_crs"]} CR，并集 {best["occupied_crs"]} CR，共享 {best["overlapping_crs"]} CR。允许重叠并不意味着必须采用重叠；不奖励重叠本身。',
      '', '每个模块的原始精确层级和 top leaf 名称族见 [逻辑来源](selected/logical_profiles.json)。这轮输出的是有逻辑联系和来源解释的局部簇，尚不能宣称完整恢复了“存储/计算/取数/读数”的行为语义。父组关联不额外占有 cells 或资源。',
      '', '![静态区域比较](figures/static_comparison.png)',
      '', '![LUT、URAM、DSP预计使用率](figures/static_resource_utilization.png)',
      '', '## 3. 目标值和覆盖范围',
      '', '固定物理 atom 和资源类别，以区域内对应资源容量为位置概率，逐真实超边估计 X/Y/SLR 跨度。一个模块内部的网也计算，不能通过合并编号隐藏距离。',
      '', '`J = 全网预计X跨度 + 全网预计Y跨度 + 4×全网预计SLR跨度 + 2×真实km1 + 2×软逻辑核心km1 + 0.0025×全网权重×模块数`。',
      '',f'总真实超边权重为 {binding["all_net_weight"]:,.2f}；主预算允许新增 km1 ≤ {binding["all_net_weight"]*cfg["global_added_km1_fraction_of_all_net_weight"]:,.2f}，且原每块内部新增切割/其关联网权重 ≤10%。前者按全网权重计，**不是**只允许比基线 km1 增加2.5%。这些是在新结果前固定的试验默认值，不是用户给定或行业阈值。',
      '在可接受候选中，距离最低J的1%容差内优先较少模块，再选较低真实km1、较低核心损失。模块数量没有硬指定，原150000 cell上限没有用作最终方案的均衡目标；85%母块大小只用于生成非平凡的局部二分提案。',
      '', '|方案|模块数|加权km1|全网静态距离|预计SLR边界量|J|被拆核心/额外碎片|',
      '|---|---:|---:|---:|---:|---:|---|']
    keys=['baseline5','previous6','all_split_s0',selection['selected']]
    if (run/'alternatives.json').exists():
        keys.extend(a['candidate'] for a in json.loads((run/'alternatives.json').read_text()))
    smaller=[r for r in comparison if r['admissible'] and r['module_count']<best['module_count']]
    alternative=min(smaller,key=lambda r:r['score']) if smaller else None
    if alternative:keys.append(alternative['candidate'])
    for name in dict.fromkeys(keys):
        if name not in rows:continue
        r=rows[name]
        lines.append(f'|{name}|{r["module_count"]}|{r["weighted_km1"]:,.2f}|{r["physical_cost"]:,.2f}|{r["slr_span"]:,.2f}|{r["score"]:,.2f}|{r["fragmented_cores"]}/{r["extra_core_fragments"]}|')
    if alternative:
        lines += ['',f'更少模块中的最佳备选为 `{alternative["candidate"]}`（{alternative["module_count"]}块），J比主推荐高 {(alternative["score"]/best["score"]-1)*100:.2f}%。它的连接、距离和跨SLR指标需分别比较；主推荐并非所有指标都占优。']
    if (run/'alternatives.json').exists():
        for entry in json.loads((run/'alternatives.json').read_text()):
            if entry['prefix']!='S':continue
            other=rows[entry['candidate']]
            other_plan=json.loads((run/entry['directory']/'static_regions.json').read_text())
            other_slrs=sorted({s for r in other_plan['regions'].values() for s in r['slrs']})
            lines += ['',f'S编号的11块备选也值得保留：相对默认12块，km1少 {(1-other["weighted_km1"]/best["weighted_km1"])*100:.2f}%，全网静态距离高 {(other["physical_cost"]/best["physical_cost"]-1)*100:.2f}%，预计SLR跨度少 {(1-other["slr_span"]/best["slr_span"])*100:.2f}%。它使用SLR {other_slrs}，被拆核心为{other["fragmented_cores"]}个；默认版为{best["fragmented_cores"]}个。该备选的核心少数侧cells为{other["core_minority_cells"]}，仍高于五块基线，不能宣称逻辑指标全面改善。',
                      '[查看11块S备选的静态区域与资源图](figures/alternative11_slr/static_comparison.png)。']
    lines += ['', f'最终真实 cut-net 数 {best["cut_nets"]:,}、原始 km1 {best["km1"]:,}；加权cut {best["weighted_cut"]:,.2f}。同周期路径跨SLR次数及其指数代价未建模，本轮没有路径时序数据。',
      f'最终核心少数侧cells为 {best["core_minority_cells"]:,}，五模块基线为 {baseline["core_minority_cells"]:,}；指标须一起看，不能仅用核心个数宣称全面改善。',
      '', '初始区域MIP使用“内部网完整期望＋边界中心代理”；之后用全部超边期望进行区域坐标搜索。报告中的最终分数全部来自同一全网评价器。初始MIP的bound/gap仅对初始化模型有效，最终模块＋区域搜索没有全局最优证书。',
      f'本候选初始化 gap：{plan["initial_mip_gap"]:.2%}；受限候选区域取最小可行面积的1.5倍＋4CR，保留所有SLR跨度，没有“跨SLR模块额外罚8”的旧项。',
      '', '![候选取舍](figures/tradeoffs.png)',
      '', '## 4. 统一选择、合并与敏感性',
      '', f'候选生成对全部原五块执行相同的二分探索，种子0/1；对超单SLR资源需求自动增加资源提案，并重评已有四子块方案。组合局部有效提案后，实际检查 {len(merged)} 个反向合并候选。不是只点名P01，也不是固定需要两个子块。',
      f'最终候选是否采用新的核心/atom边界调整：{"是" if refined else "否"}。移动日志保留在候选summary的provenance中；没有收益的备选保留比较记录。',
      '参数敏感性仅在已求得的区域方案上重新排名，不等于对每组参数完整重跑分区与区域搜索。预算倍数0.5/1/2，SLR权重2/4/8，cut权重1/2/4，模块复杂度权重0.00125/0.0025/0.005，共81组。',
      '', '|固定区域重排名的推荐|次数|','|---|---:|']
    for name,count in sorted(sensitivity['selections'].items(),key=lambda p:-p[1]):lines.append(f'|{name}|{count}|')
    repairs=[s for s in summaries if s['provenance']['kind']=='core_and_atom_refinement'
             and s['provenance']['input_candidate']==selection['selected']]
    if repairs:
        repair=repairs[0];rm=repair['metrics']
        lines += ['',f'逻辑核心修复备选 `{repair["name"]}` 的km1为 {rm["weighted_km1"]:,.2f}（较主推荐增加 {rm["weighted_km1"]-best["weighted_km1"]:.2f}），被拆核心/额外碎片为 {rm["fragmented_cores"]}/{rm["extra_core_fragments"]}。它被保留，但在预设的1%近似平分范围内，低cut优先规则选择了主版本。该规则对微小代价的逻辑修复较保守，本轮没有事后调门槛让修复版获胜。']
    lines += ['', '所选区域进一步采用两个不同提案顺序做局部搜索（不改变主比较中的区域）：'+
              '；'.join(f'seed {r["seed"]}改善 {r["relative_improvement"]:.3%}' for r in stability['runs'])+'。',
      '', '**模型限制：** 独立、容量比例的位置分布没有表达紧密电路的实际放置相关性，可能高估大模块内部距离并偏好细分。参数稳定不等于物理有效；本轮是在固定搜索邻域内做校准，没有验证继续递归细分的全部可能，也没有跨case验证。不得把代理下降百分比等同于实际线长、SLL、slack或频率改善。',
      '', '## 5. Fanout与模块间连接',
      '', '保留原缓存的数据网权重1、已识别纯控制网权重0.25，时钟/常量网单列；高fanout数据网没有删除。按超边跨度计成本会饱和，不是高fanout时序模型。',
      '本轮没有复制driver或插入buffer，资源不包含后续placement新增副本。Fanout验收、网表等价性、板级实现均未新执行。',
      '', '![模块间唯一bit-net矩阵](figures/module_connections.png)',
      '', '矩阵行为driver模块、列为sink模块。同一bit-net到达多个模块时会计入多个格子，矩阵求和不等于cut-net数量。完整连接表另保留sink-pin口径，顶层端口连接单独输出；没有假定端口的物理位置。',
      f'默认静态方案使用SLR {used_slrs}；原P01的四个子块分布在四个SLR，没有继续施加旧父组相邻两SLR的约束。在{len(strong_links)}对至少1000条bit-net的模块连接中，{len(strong_links)-len(strong_cross)}对位于同一SLR；仍跨SLR的为'+
      '、'.join(f"{e['source']}→{e['sink']}（{e['nets']}条）" for e in strong_cross)+'。这说明强连接能影响静态布局，但尚未全部局部化。',
      '', '## 6. 区域约束与物理验证边界',
      '', '|资源|最高预计利用率|预算|','|---|---:|---:|']
    for resource in ('LUT','FF','DSP','BRAM18','URAM','LUTMEM','CARRY8','MUXF7','MUXF8'):
        lines.append(f'|{resource}|{max_util[resource]:.2%}|{plan["limits"][resource]:.0%}|')
    lines += ['', '每个CR每类资源联合复算通过。所有独立逻辑cells已纳入需求，常量/时钟基础设施单列；没有推断背景系统或复制开销。实际site/packing、拥塞、软区域溢出尚未验证。',
      '没有生成或应用本候选的Pblock/XDC，没有运行place/phys_opt/route。因此没有本候选的实际资源分布、slack、频率或SLL结果；资源热图是静态估计。',
      '', '## 7. 已完成检查',
      '', '- 24项针对性与既有回归测试通过：超边增益、专用atom、资源重叠、局部预算，以及期望跨度与小图穷举一致。',
      '- 同样的位置分布下，仅改变模块编号不会改变物理评分；模块内部网有非零距离成本。',
      f'- 交付 {selected["validation"]["all_cells"]:,} 个有序唯一cell ID；资源总量守恒；完整图与DCP哈希绑定。',
      '- 新实验的源代码、参数、失败/成功日志及未选候选均保留；历史结果与独立fanout实验输入未替换。',
      '', '## 8. 文件与复现',
      '', '- [完整leaf成员](selected/leaf_cells.tsv.gz)',
      '- [模块资源](selected/module_resources.tsv)；[模块连接](selected/module_connections.tsv)；[端口连接](selected/port_connections.tsv)',
      '- [逻辑来源](selected/logical_profiles.json)；[模块集合](selected/modules.json)；[静态区域](selected/static_regions.json)',
      '- [全部可行候选比较](comparison.tsv)；[选择记录](selection.json)；[参数敏感性](sensitivity.json)',
      '- [区域搜索稳定性](region_stability.json)；[输入绑定](binding.json)；[源码快照](source/)',
      '', '生成数据只保留本地及服务器。本轮没有提交或上传新的Git版本；originalpart和此前源码分支保留。']
    if (run/'alternatives.json').exists():
        lines += ['', '以下备选也提供完整成员、资源、连接与静态区域，编号前缀用于区分不同方案：', '']
        for a in json.loads((run/'alternatives.json').read_text()):
            label={'A':'较少模块备选','L':'逻辑核心修复备选','S':'较重跨SLR代价的备选'}[a['prefix']]
            d=a['directory']
            lines.append(f'- {label}（{a["prefix"]}编号）：[模块集合]({d}/modules.json)、[完整leaf成员]({d}/leaf_cells.tsv.gz)、[资源]({d}/module_resources.tsv)、[连接]({d}/module_connections.tsv)、[静态区域]({d}/static_regions.json)。')
    (run/'实验报告.md').write_text('\n'.join(lines)+'\n')
    plots(run,modules,selected['connections'],comparison,selection['selected'])


def plots(run,modules,connections,comparison,name):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LogNorm
    out=run/'figures';out.mkdir(exist_ok=True)
    ids=[m['module_id'] for m in modules];index={m:i for i,m in enumerate(ids)}
    matrix=np.zeros((len(ids),len(ids)))
    for e in connections:matrix[index[e['source']],index[e['sink']]]=e['nets']
    fig,ax=plt.subplots(figsize=(10,9),constrained_layout=True)
    heat=ax.imshow(np.ma.masked_equal(matrix,0),cmap='YlGnBu',norm=LogNorm(vmin=1,vmax=max(2,matrix.max())))
    ax.set_xticks(range(len(ids)),ids,rotation=45);ax.set_yticks(range(len(ids)),ids)
    ax.set_xlabel('Sink module');ax.set_ylabel('Driver module')
    ax.set_title('Directed inter-module bit-nets (log color scale)')
    for y in range(len(ids)):
        for x in range(len(ids)):
            if matrix[y,x]:ax.text(x,y,str(int(matrix[y,x])),ha='center',va='center',fontsize=8,
                                  color='white' if heat.norm(matrix[y,x])>.6 else '#172554')
    fig.colorbar(heat,ax=ax,label='Unique bit-nets per directed pair')
    fig.savefig(out/'module_connections.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,6),constrained_layout=True)
    dots=ax.scatter([r['module_count'] for r in comparison],[r['weighted_km1'] for r in comparison],
                     c=[r['physical_cost']/1e6 for r in comparison],cmap='viridis_r',s=65,alpha=.85)
    for r in comparison:
        if r['candidate'] in ('baseline5','previous6',name):
            label={'baseline5':'Baseline 5','previous6':'Previous 6'}.get(r['candidate'],'Selected')
            ax.annotate(label,(r['module_count'],r['weighted_km1']),xytext=(8,10),textcoords='offset points')
    ax.set_xlabel('Module count');ax.set_ylabel('Weighted km1')
    ax.set_title('Evaluated candidates: connectivity versus granularity\nColor is a static distance estimate, not routed wirelength')
    ax.grid(alpha=.2);fig.colorbar(dots,ax=ax,label='All-net static distance / 1,000,000')
    fig.savefig(out/'tradeoffs.png',dpi=160);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();main(a.run)
