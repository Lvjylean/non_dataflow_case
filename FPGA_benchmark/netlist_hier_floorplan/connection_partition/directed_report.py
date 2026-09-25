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
    for ax,plan,title in zip(axes,[old,new],['Previous timing-based plan','New all-directed-branch plan']):
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
            grid(ax);ax.set_title(('Previous' if row==0 else 'New')+f': estimated {res}')
            cb=fig.colorbar(pic,ax=ax,fraction=.04,pad=.12,ticks=range(9));cb.ax.set_yticklabels(labels,fontsize=7)
    fig.legend(handles=[Patch(facecolor='white',edgecolor='#94a3b8',label='0%: available, unused'),
        Patch(facecolor='#e5e7eb',edgecolor='#9ca3af',hatch='///',label='No resource capacity')],loc='outside lower center',ncol=2)
    fig.suptitle('Static capacity-proportional estimates; no new placement or routing',fontsize=15)
    fig.savefig(figdir/'estimated_utilization.png',dpi=150);plt.close(fig)
    plans=[load(folder/'candidates/baseline_original.json'),load(folder/'candidates/baseline_current.json'),new]
    fig,axes=plt.subplots(1,3,figsize=(16,4.7),layout='constrained')
    for ax,family,title in zip(axes,['matA_write_64','matB_read_all','matB_read_bit62'],['matA write: all 64 nets','matB source: all 65 output nets','matB read: bit 62']):
        xs=np.arange(4)
        for i,(plan,label,color) in enumerate(zip(plans,['Original','Previous','New'],['#cbd5e1','#f59e0b','#0284c7'])):
            hist=plan['families'][family]['expected_boundary_histogram']
            ax.bar(xs+(i-1)*.25,[hist.get(str(x),0) for x in xs],width=.25,label=label,color=color)
        ax.set_xticks(xs);ax.set_xlabel('Single driver-to-sink SLR boundaries');ax.set_ylabel('Expected original sink pins');ax.set_title(title);ax.legend()
    fig.suptitle('Static communication estimates, not physical SLL counts or timing measurements')
    fig.savefig(figdir/'directed_projection.png',dpi=160);plt.close(fig)

def report(folder):
    new=load(folder/'solution.json');previous=load(folder/'candidates/baseline_current.json');original=load(folder/'candidates/baseline_original.json')
    meta=load(folder/'input/export/modules.json');data=load(folder/'directed.json');binding=load(folder/'binding.json')
    verify=load(folder/'verification.json');loc=load(folder/'location.json');comparison=load(folder/'comparison.json')
    plots(folder);mods=meta['modules'];cfg=new['configuration'];now=new['components'];old=previous['components']
    lines=['# TRTRS：固定11模块，全网有向分支增强 floorplan','',
        '**状态：静态求解、固定成员导出和独立复算完成；未运行新的placement、route或STA。Fanout改写、物理区域和时序验证均未执行。**','',
        f'保持 S00–S10 的成员不变。新目标 J 相对上一轮区域下降 {1-now["J"]/old["J"]:.2%}；原始11模块区域也使用同一新目标重算，避免混用目标值。','',
        '## 1. 输入与范围','',f'服务器 eda070；独立实验目录：`{loc["run"]}`。',
        f'输入 post-opt DCP：`{binding["input_dcp"]}`。SHA256：`{binding["input_sha256"]}`。',
        f'完整 leaf cells {binding["total_leaf_cells"]:,}，其中11个模块内逻辑 cells {binding["logical_cells"]:,}；25,800个常量和1个旧分类CLOCK单列。包含 {sum(m["top_direct_cells"] for m in mods):,} 个top直属逻辑cells。',
        '复用同一份优化后网表、原始driver/sink缓存和固定模块集合。所有11模块均有模块间连接；本轮没有孤立模块被排除。模块仍保留既有逻辑来源，未重组层级、未增加DSP子层、未改变matB成员或插入寄存器。',
        'U250的4个SLR均为候选。各模块使用CR矩形，可跨SLR并与其他模块重叠。区域面积不超过最小资源可行面积的1.5倍加4CR。URAM上限100%，其余8类资源70%，同时检查单模块和逐CR叠加；沿用该轮规则，不另加历史50%整SLR规则。',
        '本次变化仅为floorplan成本：使用所有可定位原始有向分支，停用上一轮995条路径的关键度加权项。不累计两个各跨一边界的分支，不使用归一化。系数在搜索前固定。','',
        '## 2. 求解结果','',
        '|模块|cells|LUT|FF|DSP|BRAM18|URAM|上一轮区域|本轮区域|','|---|---:|---:|---:|---:|---:|---:|---|---|']
    def rt(r):
        x0,y0,x1,y1=r['bounds'];return ','.join('SLR'+str(s) for s in r['slrs'])+f' / X{x0}Y{y0}:X{x1}Y{y1}'
    for m in mods:
        mid=m['module_id'];lines.append('|'+ '|'.join([mid,*[str(m[k]) for k in ['cells','LUT','FF','DSP','BRAM18','URAM']],rt(previous['regions'][mid]),rt(new['regions'][mid])])+'|')
    lines+=['','原始逻辑来源沿用固定模块文件，主要层级贡献如下（不把算法模块编号解释成新RTL层级）：','',
        '|模块|主要原始owner及cell数|','|---|---|']
    for m in mods:
        owners=m['original_owners'];lines.append(f'|{m["module_id"]}|'+str(owners[:3] if isinstance(owners,list) else dict(list(owners.items())[:3])).replace('|','/')+'|')
    lines+=['',f'区域面积之和 {new["total_module_crs"]} CR；并集 {new["overlap"]["occupied_crs"]} CR；共享 {new["overlap"]["overlapping_crs"]} CR。',
        'SLR1：S02/S04/S06/S07/S09；SLR2：S00/S03/S05/S08/S10；SLR3：S01。SLR0未选用。S02与S06共享完整区域，S03与S08共享完整区域，S07位于S04区域内部。',
        '各模块需求按矩形内相应资源容量比例分配，逐CR把所有重叠模块的同类资源利用率相加。常量/时钟基础设施和未来复制helper没有附加到模块静态预算。','',
        '|资源|最高CR预计利用率|上限|','|---|---:|---:|']
    for r,v in new['overlap']['maximum_utilization'].items():lines.append(f'|{r}|{v:.3%}|{new["limits"][r]:.0%}|')
    lines+=['','![上一轮和本轮区域](figures/regions.png)','',
        '![LUT、URAM和DSP预计资源利用率](figures/estimated_utilization.png)','',
        '图中0%为白底并标0%；无该资源容量为灰色斜线；非零使用独立蓝色档位。这些是资源比例估计，不是实际placement。','',
        '## 3. 目标值和覆盖范围','',
        '`J = D_all + C_fixed + D_dir + 32 P_branch`。',
        '`D_all = Σ_e w_e E[spanX(e)+spanY(e)+4 spanSLR(e)]`，保留原全网超边模型，模块内部网也计价。',
        '`D_dir = Σ_e w_e Σ_(sink pins t) E[|X_driver−X_t|+|Y_driver−Y_t|+4|SLR_driver−SLR_t|]`。',
        '`P_branch = Σ_e w_e Σ_t E[max(0,|SLR_driver−SLR_t|−1)^2]`。单分支跨0/1/2/3个边界的额外成本分别为0/0/32/128，再乘网权重。两条各跨一个边界的分支不触发累计平方惩罚。',
        '数据网权重1，沿用原缓存纯控制网权重0.25。保留每个原始sink pin的数量，包括同一接收cell上的多个pin；不是每模块对只计一次。源端位置改变会改变广播的分支星形代价，虽然单对距离本身对称。',
        '原始物理atom内部连接距离取0。同一资源类别中不同atom独立按CR资源容量分布，因此同模块连接也不免费。平方在各SLR位置组合上求期望，而不是对平均SLR距离平方。C_fixed为固定partition的cut/逻辑核心/模块数量成本，本轮是常数。','',
        '|分量|原始11模块区域|上一轮区域|本轮区域|','|---|---:|---:|---:|']
    for k,label in [('physical_cost','D_all'),('slr_span','超边加权SLR跨度'),('fixed_partition_cost','C_fixed'),('directed_distance','D_dir'),('directed_internal_distance','D_dir中模块内部距离'),('directed_slr','有向分支加权边界总量'),('branch_square','P_branch'),('branch_square_term','32 P_branch'),('raw_far_pins','预计跨至少2边界原始sink pins'),('raw_branch_boundaries','原始sink分支边界总量'),('J','新目标J')]:
        lines.append('|'+label+'|'+'|'.join(f'{p["components"][k]:,.4f}' for p in [original,previous,new])+'|')
    lines+=['',f'相对上一轮：全网超边距离变化 {now["physical_cost"]/old["physical_cost"]-1:+.2%}，有向距离变化 {now["directed_distance"]/old["directed_distance"]-1:+.2%}。新J减少不意味着每个原有指标都减少。','',
        '|广播族|网数 / sink pins|原始远端pins|上一轮远端pins|本轮远端pins|','|---|---:|---:|---:|---:|']
    for f,label in [('matA_write_64','matA全部64位写广播'),('matB_read_all','matB源BRAM全部输出网'),('matB_read_bit62','matB读bit62（上行子集）')]:
        family=new['families'][f];lines.append(f'|{label}|{family["nets"]} / {family["sink_pins"]}|'+'|'.join(f'{p["families"][f]["far_sink_pins"]:,.2f}' for p in [original,previous,new])+'|')
    lines+=['','本轮剩余17个远端sink pins全部来自S07的FF代表资源→S01的LUT代表资源，SLR1→SLR3；加权平方成本为544，已计入J。没有因数量较小将其过滤，也没有声称已消除全部远距离路径。',
        '远端指单分支跨至少两个SLR边界。这些广播仅用于解释结果，优化器没有为这些名字配置额外权重或硬约束。原始sink分支数量不是复制后的实际SLL线数，也不能直接换算slack。','',
        '![广播分支跨度对照](figures/directed_projection.png)','',
        '|原始有向缓存覆盖项|数量|','|---|---:|']
    for k,v in data['coverage'].items():lines.append(f'|{k}|{v:,}|')
    lines+=['','顶层端口、未分配基础设施端点没有候选位置，其排除量已单列；不把这些连接误认为不存在。完整端口连接保留在固定导出中。原缓存此前已排除常量及其旧CLOCK分类网；该分类含BUFG驱动基础设施，本轮没有新增真实时钟审计。',
        '本轮没有提取STA路径，因此没有全同周期路径覆盖保证。没有预测后续driver复制、拥塞、实际落点、布线绕行或clock skew；同一大区域内的容量比例位置仅为静态代理。',
        f'共记录 {len(comparison)} 个可行候选；选中 `{new["tag"]}`，搜索耗时 {new["runtime_seconds"]:.1f}s。保留原始和上一轮方案，枚举可行die重排；两个种子的联合MIP提出候选；三个起点以全部保留矩形作局部移动及模块区域交换，最多5轮。最终全部使用精确静态J排名，同分按全网远端pin数和候选名称排序。',
        'MIP采用跨模块资源位置均值的距离/平方近似，模块内部项使用精确静态期望。MIP的bound/gap只适用于提案近似模型，不是最终J的全局最优证书；最终结果是本次搜索找到的最佳可行方案。','',
        '|MIP种子|状态|近似incumbent|近似bound|近似gap|秒|','|---|---|---:|---:|---:|---:|']
    for r in comparison:
        if r['tag'].startswith('mip_'):
            a=r['extra'];lines.append(f'|{a["seed"]}|{a["status"]}|{a["objective"]:,.3f}|{a["bound"]:,.3f}|{a["gap"]:.2%}|{a["runtime"]:.2f}|')
    lines+=['','## 4. Fanout 处理','',
        '本轮未改写网表或复制driver，未插入分发树/寄存器，也没有增加周期。缓存中的原始fanout通过分支数量参与成本。所有BRAM/URAM/FD/LUT实际复制数量、阈值验收、各级负载集合、恒等逻辑和功能等价性验证均未执行；沿用成员不等于后续复制结果已验证。','',
        '### 原有通用复制策略的验收结果','',
        'place/phys_opt/route/最终重开均未执行；本轮没有新的逻辑或物理fanout证书，未复用旧证书冒充本轮通过。后续实验可用既有fanout流程，但应以新落点重新核验。','',
        '## 5. 约束验证和物理实现','',
        f'独立CR几何、九类资源、全网成本与分支成本复算：{verify["status"]}。成员、资源和连接导出逐字节不变。原输入DCP和既有缓存摘要复核通过。',
        f'后续实现输入已准备：`{loc["run"]}/implementation_input/`。`membership.tsv`包含完整leaf归属，`regions.tcl`提供CR区域数据，须经既有软Pblock入口加载；它不是独立完整XDC。',
        '本轮未执行Vivado约束绑定；IS_SOFT、site几何、实际区域内外primitive比例和新增helper占用须在下次实现检查。规划70%不等于Vivado硬密度限制。',
        '上一轮fastfanout实际WNS +0.091ns、WHS +0.019ns仅作历史参考（10ns OOC范围）。本轮未测量WNS/WHS/TNS/THS、routing/DRC、I/O约束或未约束端点，也没有新的最差路径延迟分解。',
        '最终布线DCP：未生成；大小/SHA不适用。实际DSP分布、各模块区域内外数量及SLR primitive分布：未执行，不绘制假定的实际布局图。','',
        '|阶段|时序|routing/DRC|区域内外/实际DSP|','|---|---|---|---|','|place|未执行|未执行|未执行|','|phys_opt|未执行|未执行|未执行|','|route及独立重开|未执行|未执行|未执行|','',
        '## 6. 已完成测试','',
        '- 17项小模型/回归检查通过，包括单分支平方、两条单边界分支不累计、同超边跨度下源位置差异、sink数量/控制权重、平方期望、内部atom和参数传递。',
        '- 独立进程用CR对显式枚举复算全部有向资源对，用概率乘积复算超边跨度；原始、上一轮和新方案全部一致。',
        f'- {verify["immutable_input_count"]}个既有输入文件摘要不变；post-opt DCP摘要和搜索源快照核验通过。',
        '- 适配器检查755385个leaf名称、唯一成员和所有模块资源汇总，再生成实现输入；图像及本地交付摘要另行核验。',
        '- 未执行新的fanout改写、布线、物理site或功能等价性测试。','',
        '## 7. 文件','',
        '- [结果](solution.json)、[候选对照](comparison.json)、[独立复算](verification.json)。',
        '- [固定模块](export/modules.json)、[leaf成员](export/leaf_cells.tsv.gz)、[资源](export/module_resources.tsv)、[模块连接](export/module_connections.tsv)、[逻辑来源](export/logical_profiles.json)、[端口连接](export/port_connections.tsv)。',
        '- [静态区域](export/static_regions.json)、[实现区域数据](implementation_input/regions.tcl)、[实现输入核验](implementation_input/manifest.json)。',
        '- [全部有向聚合与覆盖](directed.json)、[输入绑定](binding.json)、[运行位置](location.json)、[源码快照](source/)。',
        '- [交付摘要](delivery_manifest.json)。源码和网表派生结果只保存于工作区/已授权服务器；本轮没有Git提交或上传。']
    (folder/'实验报告.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':report(Path(sys.argv[1]))
