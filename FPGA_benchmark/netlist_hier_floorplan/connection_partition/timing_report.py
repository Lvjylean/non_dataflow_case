"""Seven-section static floorplan report with explicit unrun physical stages."""
import csv
import json
from pathlib import Path
import sys


def load(p):return json.loads(p.read_text())


def plots(folder):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import ListedColormap,BoundaryNorm
    from matplotlib.patches import Rectangle,Patch
    new=load(folder/'solution.json');old=load(folder/'input/export/static_regions.json')
    device={}
    for r in csv.DictReader((folder/'input/cr.tsv').open(),delimiter='\t'):
        n=int(r['SLICEL'])+int(r['SLICEM'])
        device[r['cr']]=dict(x=int(r['x']),y=int(r['y']),LUT=8*n,URAM=int(r['URAM']),DSP=int(r['DSP']))
    figdir=folder/'figures';figdir.mkdir(exist_ok=True)
    def grid(ax):
        ax.set_xlim(-.5,7.5);ax.set_ylim(-.5,15.5);ax.set_aspect('equal')
        ax.set_xticks(range(8));ax.set_yticks(range(16))
        ax.set_xticks(np.arange(-.5,8,1),minor=True);ax.set_yticks(np.arange(-.5,16,1),minor=True)
        ax.grid(which='minor',color='#cbd5e1',lw=.5);ax.tick_params(which='minor',length=0)
        ax.set_xlabel('Clock-region X');ax.set_ylabel('Clock-region Y')
        for y in (3.5,7.5,11.5):ax.axhline(y,color='#334155',lw=1.5)
        for s in range(4):ax.text(7.7,4*s+1.5,f'SLR{s}',fontsize=9,va='center')
    fig,axes=plt.subplots(1,2,figsize=(12,11),layout='constrained')
    palette=plt.get_cmap('tab20');leg=[]
    for ax,plan,title in zip(axes,[old,new],['Original 11-module plan','New timing-aware 11-module plan']):
        grid(ax);ax.set_title(title)
        for i,(mid,r) in enumerate(sorted(plan['regions'].items())):
            x0,y0,x1,y1=r['bounds'];color=palette(i)
            ax.add_patch(Rectangle((x0-.5,y0-.5),x1-x0+1,y1-y0+1,facecolor=(*color[:3],.12),edgecolor=color,lw=2))
            ax.text(x0-.3,y0-.22+.3*(i%3),mid,fontsize=10,fontweight='bold',
                    bbox=dict(facecolor='white',alpha=.9,edgecolor='none',pad=1))
        if not leg:leg=[Patch(facecolor=palette(i),label=m) for i,m in enumerate(sorted(plan['regions']))]
    fig.legend(handles=leg,loc='outside lower center',ncol=11,fontsize=9)
    fig.savefig(figdir/'regions.png',dpi=160);plt.close(fig)
    thresholds=[.01,.05,.1,.2,.4,.6,.8,1,float('inf')]
    labels=['>0-1%','>1-5%','>5-10%','>10-20%','>20-40%','>40-60%','>60-80%','>80-100%','>100%']
    cmap=ListedColormap(['#b1dff0','#79c9e4','#42b0d2','#188daf','#116b99','#21518a','#30366f','#171c49','#b91c1c'])
    cmap.set_bad((1,1,1,0));norm=BoundaryNorm(np.arange(-.5,9.5),9)
    fig,axes=plt.subplots(2,3,figsize=(18,19),layout='constrained')
    for row,plan in enumerate([old,new]):
        usage={r['cr']:r['utilization'] for r in plan['overlap']['contributions']}
        for col,res in enumerate(['LUT','URAM','DSP']):
            ax=axes[row,col];values=np.full((16,8),np.nan)
            for cr,d in device.items():
                if d[res]:values[d['y'],d['x']]=usage.get(cr,{}).get(res,0)
            bands=np.searchsorted(thresholds,values,side='left')
            pic=ax.imshow(np.ma.array(bands,mask=~(np.isfinite(values)&(values>0))),origin='lower',cmap=cmap,norm=norm,interpolation='nearest')
            for y in range(16):
                for x in range(8):
                    v=values[y,x]
                    if not np.isfinite(v):
                        ax.add_patch(Rectangle((x-.5,y-.5),1,1,facecolor='#e5e7eb',edgecolor='#9ca3af',hatch='///',lw=0));continue
                    text='0%' if v==0 else '<0.1%' if v<.001 else f'{v:.1%}' if v<.01 else f'{v:.0%}'
                    ax.text(x,y,text,ha='center',va='center',fontsize=7,color='white' if v>0 and bands[y,x]>=3 else '#334155')
            grid(ax);ax.set_title(('Original' if row==0 else 'New')+f': estimated {res}')
            cb=fig.colorbar(pic,ax=ax,fraction=.04,pad=.12,ticks=range(9));cb.ax.set_yticklabels(labels,fontsize=7)
    fig.legend(handles=[Patch(facecolor='white',edgecolor='#94a3b8',label='0%: available, unused'),
        Patch(facecolor='#e5e7eb',edgecolor='#9ca3af',hatch='///',label='No resource capacity')],loc='outside lower center',ncol=2)
    fig.suptitle('Static capacity-proportional estimates; no new placement or routing',fontsize=15)
    fig.savefig(figdir/'estimated_utilization.png',dpi=150);plt.close(fig)
    baseline=load(folder/'candidates/baseline.json')
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    for ax,key,title in [(axes[0],'path','Projected critical paths'),(axes[1],'broadcast','All 1,024 original broadcast sinks')]:
        before=baseline['components']['path_boundary_histogram'] if key=='path' else baseline['broadcast']['expected_boundary_histogram']
        after=new['components']['path_boundary_histogram'] if key=='path' else new['broadcast']['expected_boundary_histogram']
        xs=np.array(sorted(set(map(int,before))|set(map(int,after))))
        ax.bar(xs-.18,[before.get(str(x),0) for x in xs],width=.36,label='Original',color='#94a3b8')
        ax.bar(xs+.18,[after.get(str(x),0) for x in xs],width=.36,label='New',color='#0284c7')
        ax.set_xticks(xs);ax.set_xlabel('Cumulative SLR boundaries' if key=='path' else 'Driver-to-sink SLR span')
        ax.set_ylabel('Expected count');ax.set_title(title);ax.legend()
    fig.suptitle('Model projections, not new routed measurements')
    fig.savefig(figdir/'critical_projection.png',dpi=160);plt.close(fig)


def report(folder):
    new=load(folder/'solution.json');baseline=load(folder/'candidates/baseline.json');old=baseline['components'];now=new['components']
    meta=load(folder/'input/export/modules.json');feedback=load(folder/'feedback.json');binding=load(folder/'binding.json')
    verify=load(folder/'verification.json');loc=load(folder/'location.json');comparison=load(folder/'comparison.json')
    plots(folder)
    cfg=new['configuration'];coverage=feedback['coverage'];mods=meta['modules']
    lines=['# TRTRS：固定 11 模块的新目标 floorplan','',
        '**状态：静态 floorplan 求解、成员绑定、资源约束和独立目标复算完成。未重新 partition，未运行新的 placement、route 或 STA。**','',
        f'固定 S00-S10，共 {sum(m["cells"] for m in mods):,} 个模块内逻辑 cells。新目标 J 从 {old["J"]:,.2f} 降至 {now["J"]:,.2f}，下降 {(1-now["J"]/old["J"]):.2%}。',
        f'完整 `gmem1_RDATA[62]` 广播的 1,024 个原始 sink 中，预计跨至少两个 SLR 边界的负载从 {baseline["broadcast"]["expected_far_sink_pins"]:g} 降至 {new["broadcast"]["expected_far_sink_pins"]:g}。这是区域模型结果，不是新 WNS 或实际 SLL 测量。','',
        '## 1. 输入与范围','',f'服务器：eda070。新实验目录：`{loc["run"]}`。',
        f'原始 post-opt DCP：`{binding["post_opt_dcp"]}`，SHA256 `{binding["post_opt_sha256"]}`。',
        f'时序反馈：`{binding["timing_binding"]["dcp"]}`，SHA256 `{binding["timing_binding"]["sha256"]}`。',
        '模块成员、资源需求、连接表和逻辑来源逐字节保持不变；只有 static_regions 及其新成本改变。所有四个 SLR 均可选，允许多 SLR 矩形和区域重叠。没有 cell 数均衡或固定 die 数约束。',
        '器件为 U250，沿用原 CR 窗口：面积不超过最小资源可行面积的 1.5 倍再加 4 CR。九类资源中，URAM 预算为100%，其余八类为70%；不额外套用历史整SLR50%规则。完整已分配逻辑包含 top-direct cells，时钟和常量基础设施保持原单列方式。',
        '所有11个模块均有完整网表中的模块间连接，本轮无需排除孤立模块。保持原物理 atom 和原始逻辑来源；没有新增 DSP 子层或层级重组。固定成员来自先前 KaHyPar 流程，本轮只求解各模块的矩形区域。','',
        '## 2. 求解结果','',
        '|模块|cells|LUT|FF|DSP|BRAM18|URAM|原 SLR / CR|新 SLR / CR|',
        '|---|---:|---:|---:|---:|---:|---:|---|---|']
    def region_text(r):
        x0,y0,x1,y1=r['bounds'];return ','.join('SLR'+str(s) for s in r['slrs'])+f' / X{x0}Y{y0}:X{x1}Y{y1}'
    for m in mods:
        mid=m['module_id'];lines.append('|'+ '|'.join([mid,*[str(m[k]) for k in ['cells','LUT','FF','DSP','BRAM18','URAM']],region_text(baseline['regions'][mid]),region_text(new['regions'][mid])])+'|')
    lines += ['',f'新区域面积之和 {new["total_module_crs"]} CR，并集 {new["overlap"]["occupied_crs"]} CR，其中 {new["overlap"]["overlapping_crs"]} CR 由多个模块共享。资源叠加检查全部通过。模块编号保持原有意义，不新增层级或拆分。',
        'S10 广播源与原最差路径接收端所在的 S08 同在 SLR1；S10、S05、S06、S08 在 SLR1，S01、S03 在 SLR2，其他五个模块在 SLR0。S00/S02 共享6个CR，S04/S09共享6个CR。SLR3仍是合法候选，本次结果未使用。',
        '上述共享检查将模块资源相加：每个模块按区域内对应资源容量分配需求，所有模块在每个CR中的比例之和受限。没有把不同模块的资源重复视为可独占容量。',
        '', '|资源|新方案最高CR预计使用率|上限|','|---|---:|---:|']
    for res,value in new['overlap']['maximum_utilization'].items():
        lines.append(f'|{res}|{value:.3%}|{new["limits"][res]:.0%}|')
    lines += ['',
        '资源图是容量比例分布估计，不是实际 placement。0% 为白色并明确标0，无该资源容量的 CR 为灰色斜线；所有正利用率使用独立蓝色档位。','',
        '![原、新区域](figures/regions.png)','', '![原、新LUT、URAM、DSP估计利用率](figures/estimated_utilization.png)','',
        '## 3. 目标值和覆盖范围','',
        '`J = D_all + fixed_partition_cost + 10*C_critical + 100*P_square`，没有除以目标基准、路径数或权重总和。',
        '`D_all = Σ_e w_e E[spanX + spanY + 4*spanSLR]`，沿用完整原始信号超图，内部网络也计价。',
        '`C_critical = Σ_(u,v) q_uv E[|ΔX| + |ΔY| + 4|ΔSLR|]`，按唯一有序原始 atom 对计价，同对从多条反馈路径出现时取最大关键度。',
        '`P_square = Σ_p q_p E[(max(0,Σ_(u,v in p)|SLR(u)-SLR(v)|-1))^2]`。每条路径保持原有同周期顺序；同一 atom 重复出现时共享位置，不独立重采样。',
        '`q = 1 + 9*clip(1-slack/0.5ns,0,1)`。关键度来自固定反馈 DCP，在本轮搜索期间不变。10 和100是在结果产生前确定的原始尺度试验系数，不是物理延迟常数。',
        '位置按每个原始 atom 的代表资源在矩形内的容量比例分布。原有全网模型和新连接模型均考虑区域内距离；路径项计算平方的期望，不能用平均 SLR 的平方替代。',
        '', '|分量|原区域重算|新区域|','|---|---:|---:|']
    for key,label in [('physical_cost','完整网络物理代理 D_all'),('slr_span','完整网络加权SLR跨度'),('fixed_partition_cost','固定 partition 项'),('critical_connection_distance','关键连接原始量 C_critical'),('critical_connection_term','10*C_critical'),('weighted_path_square','加权平方原始量 P_square'),('path_square_term','100*P_square'),('path_expected_boundaries','反馈路径预计边界总数'),('path_expected_over_one','反馈路径预计跨至少两边界数量'),('J','新目标 J')]:
        lines.append(f'|{label}|{old[key]:,.4f}|{now[key]:,.4f}|')
    lines += ['',f'原有 J（不含新时序项）从 {old["old_J"]:,.2f} 变为 {now["old_J"]:,.2f}，需要与新目标分别阅读。原 km1 和逻辑核心分量为固定常数；降低新 J 不代表所有旧指标同时改善。',
        f'具体代价：完整网络物理代理增加 {now["physical_cost"]/old["physical_cost"]-1:.2%}，完整网络加权SLR跨度增加 {now["slr_span"]/old["slr_span"]-1:.2%}。本次改善集中在采样关键路径及补齐广播分支，不能称为全设计SLL或跨die连线总量减少。',
        '仍有4条投影路径为 S10→S07→S08，形成 SLR1→SLR0→SLR1，累计两边界，关键度均为1。其平方项总成本400已计入；本次没有将所有跨多边界路径设成硬禁令。',
        f'反馈覆盖：1,000 条原生 unique-pin 最差 setup 路径，去除辅助分发逻辑、映射原始 atom 并去重后 {coverage["projected_unique_paths"]} 条。成功映射 {coverage["mapped_cells"]} 个 routed cells，另有 {coverage["excluded_auxiliary_cells"]} 个新增 identity/BUFG 分发节点投影移除。所有反馈路径首尾均有原始归属。',
        f'来自路径的有序 atom 对 {coverage["observed_unique_atom_connections"]} 个；对已识别广播补齐全部 1,024 个原始 sink 后共 {coverage["complete_feedback_connections"]} 对，新增 {coverage["added_broadcast_connections"]} 对。补齐部分使用该源 BRAM 的最大观测关键度，属于保守传播，不宣称每个 sink 都有实测 slack。',
        f'原最差路径 slack +0.032ns 对应 q=9.424。完整广播在新区域中的最大有支持的 SLR 分支跨度为 {new["broadcast"]["maximum_supported_branch_span"]}。',
        f'原始清单含 {meta["inventory"]["signal_nets"]:,} 个 signal nets、{meta["inventory"]["signal_sink_pins"]:,} 个 signal sink pins；保留 {meta["inventory"]["atoms"]:,} 个原始 atom，完整超图包含 {meta["inventory"]["hyperedges"]:,} 条至少跨两个 atom 的加权超边。25800个常量cell与1个时钟cell单列。控制连接沿用原图的固定权重，不按本次路径出现次数修改。',
        f'包括 {sum(m["top_direct_cells"] for m in mods):,} 个 top-direct logic cells，均已分配模块。顶层端口连接完整保存在 port_connections.tsv；本轮没有已绑定的物理PORT位置，因此没有为PORT虚构距离。atom内部专用连接保持原绑定，不单独估计内部距离。',
        '时序集合不是全设计路径穷举。移除 helper 后的路径投影不预测未来 fanout 树、布线绕行、clock skew 或局部拥塞；多SLR矩形中的独立位置分布也不是真实 placer 行为。原生1000条路径的实际跨界数与这里995条投影路径的计数口径不同，不能混用。','',
        '![关键路径和完整广播的模型对照](figures/critical_projection.png)','',
        f'共记录 {len(comparison)} 个可行候选，选中 `{new["tag"]}`，搜索耗时 {new["runtime_seconds"]:.1f}s。先枚举原矩形的 die 重排，再进行两个种子的联合区域提案和局部移动/交换。每次接受和最终排名均使用上述完整静态 J。',
        '联合 MIP 使用中心距离近似产生起点，其 bound/gap 只适用于该近似子问题，不是最终 J 的全局最优证书。候选中的原方案始终保留。同完整J时按广播远端数量、候选名称排序。新配置统一传入全网成本和新成本，修复了原局部搜索固定写死4的参数问题，默认4下原结果重算保持一致。',
        '', '|联合提案种子|状态|近似目标 incumbent|近似 bound|近似 gap|耗时(s)|','|---|---|---:|---:|---:|---:|']
    for seed in cfg['mip_seeds']:
        status=load(folder/f'candidates/mip_{seed}.json')['extra']
        lines.append(f'|{seed}|{status["status"]}（时间上限，有可行解）|{status["objective"]:,.3f}|{status["bound"]:,.3f}|{status["gap"]:.2%}|{status["runtime"]:.2f}|')
    lines += ['',
        '## 4. Fanout 处理','',
        '本轮未修改网表，未生成 driver 副本或新增寄存器。复用之前 routed DCP 的分发结果作为诊断来源；原普通逻辑 fanout<100 的检查不能自动成为新 floorplan 的验收结果。',
        '### 原有通用复制策略的验收结果','',
        '本轮 placement/phys_opt/route/重新打开阶段均未执行，所有新 fanout、helper 局部性和功能等价性测量均未执行。完整广播检查只评价原始 sink 在候选区域中的 SLR 关系，不是电气 fanout 证书。','',
        '## 5. 约束验证和物理实现','',
        '已独立核验矩形CR集合、模块资源可容纳性和逐CR九类资源叠加。所有原始成员、资源和连接文件与输入逐字节相同。导出继续使用原有软区域语义。',
        '本轮未运行 Vivado，未生成新的 routed DCP；新的 WNS/WHS/TNS/THS、routing/DRC、实际 primitive 区域内外统计及实际 DSP 分布均为未执行，不绘制伪造的实际占用图。最终DCP大小和摘要不适用。原 DCP 的 WNS +0.032ns 仅作10ns OOC基准，不是板级/平台时序保证。',
        '软区域约束由既有实现入口读取 regions.tcl 和 membership.tsv 后建立；regions.tcl 是区域数据，不是可单独执行的完整XDC。IS_SOFT、site合法性和成员区域内外情况需在下一次实现中复核。估计70%不是Vivado中的硬密度限制。新增复制/helper资源尚未计入本次静态需求。',
        f'可供后续实现使用的输入：`{loc["run"]}/implementation_input/`。其中 membership.tsv 与 regions.tcl 由既有适配器生成；本轮只生成输入，没有执行这些约束。',
        '原始 post-opt 和 routed checkpoint 均保留服务器原路径；历史结果指针不变。',
        '', '|阶段|WNS/WHS/TNS/THS|routing/DRC|成员区域内外/实际DSP|','|---|---|---|---|',
        '|place|未执行|未执行|未执行|','|phys_opt|未执行|未执行|未执行|','|route及独立重开|未执行|未执行|未执行|','',
        '## 6. 已完成测试','',
        '- 20项小模型检查通过：跨两边界、往返、重复atom相关性、平方期望、关键度、配置系数及原有全网模型回归。',
        f'- 独立进程使用超边概率乘积、CR对枚举、路径SLR完整离散枚举重算原方案与新方案，结果 {verify["status"]}。',
        f'- {verify["immutable_inputs"]} 个既有输入文件摘要复核不变；成员/资源/连接等导出文件逐字节不变。',
        '- 既有实现输入适配器重新检查755385个原始leaf名称/唯一ID/模块资源总量及post-opt DCP绑定。',
        '- 区域/资源图视觉复核及本地证据哈希核验见交付清单。','',
        '## 7. 文件','',
        '- [新区域与完整结果](solution.json)；[候选比较](comparison.json)；[独立复算](verification.json)。',
        '- [固定模块集合](export/modules.json)；[完整leaf成员](export/leaf_cells.tsv.gz)；[资源](export/module_resources.tsv)；[连接](export/module_connections.tsv)；[逻辑来源](export/logical_profiles.json)；[端口连接](export/port_connections.tsv)。',
        '- [新静态区域](export/static_regions.json)；[后续实现区域输入](implementation_input/regions.tcl)；[输入适配核验](implementation_input/manifest.json)。',
        '- [固定反馈及投影来源](feedback.json)；[输入绑定](binding.json)；[运行位置](location.json)；[源码快照](source/)。',
        '- [交付文件摘要](delivery_manifest.json)。本轮没有Git提交或上传。']
    (folder/'实验报告.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':report(Path(sys.argv[1]))
