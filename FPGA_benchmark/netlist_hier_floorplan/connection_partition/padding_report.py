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
    for ax,plan,title in zip(axes,[old,new],['Core planning regions','Exported soft Pblocks: RAM >80%, +1 X column']):
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
            grid(ax);ax.set_title(('Core' if row==0 else 'Soft envelope')+f': estimated {res}')
            cb=fig.colorbar(pic,ax=ax,fraction=.04,pad=.12,ticks=range(9));cb.ax.set_yticklabels(labels,fontsize=7)
    fig.legend(handles=[Patch(facecolor='white',edgecolor='#94a3b8',label='0%: available, unused'),
        Patch(facecolor='#e5e7eb',edgecolor='#9ca3af',hatch='///',label='No resource capacity')],loc='outside lower center',ncol=2)
    fig.suptitle('Static capacity-proportional estimates; no new placement or routing',fontsize=15)
    fig.savefig(figdir/'estimated_utilization.png',dpi=150);plt.close(fig)

def report(folder):
    new=load(folder/'solution.json');core=load(folder/'core_solution.json');meta=load(folder/'export/modules.json')
    binding=load(folder/'binding.json');verify=load(folder/'verification.json');loc=load(folder/'location.json')
    changes=new['soft_padding']['changes'];mods=meta['modules'];events={e['module']:e for e in changes}
    plots(folder)
    def region(r):
        x0,y0,x1,y1=r['bounds'];return ','.join('SLR'+str(s) for s in r['slrs'])+f' / X{x0}Y{y0}:X{x1}Y{y1}'
    lines=['# TRTRS：RAM超过80%时向右扩一列的软Pblock版本','',
        '**状态：软Pblock导出、完整成员绑定、静态资源与成本复算完成。未重新partition或搜索floorplan，未执行新的placement、route、STA或fanout处理。**','',
        '保持原11模块及规划区域；仅导出阶段按规则扩大软Pblock。S02、S03、S10向右扩到X7；S04已经到X7，记录器件边界截断并保持不变。','',
        '## 1. 输入与范围','',f'服务器：eda070。独立目录：`{loc["run"]}`。',
        f'原规划：`{binding["previous"]}/export/static_regions.json`。',
        f'输入post-opt DCP：`{binding["input_dcp"]}`；SHA256：`{binding["input_sha256"]}`。',
        '11个S00–S10模块的成员、逻辑来源、资源需求与连接文件逐字节保持不变；755385个leaf中729584个归入模块，25800个常量与1个旧CLOCK分类基础设施单列。133097个top直属逻辑cells已纳入模块。所有11模块均有模块间连接，无孤立模块排除。',
        'URAM规划上限仍为100%，不改成80%；其余资源继承原规划设置（包括BRAM18当前70%）。RAM触发逐类检查URAM和BRAM18，不把两类容量相加；LUTMEM仍按LUT相关资源处理。本例触发均来自URAM。',
        '定义u(m,r)=模块需求/原规划区域容量；若任一RAM类型u>0.8，则实际导出的右边界x1_soft=min(x1_core+1,器件最右CR列)，其余三个边界不变。恰好80%不触发，零需求不触发。以原规划区域检测，重复输入已扩展结果会被拒绝，避免每次导出再扩一列。',
        '本轮扩展整个模块的CLOCKREGION软Pblock范围，因此SLICE/DSP/BRAM等可用范围一起扩展；没有拆分URAM与LUT子区域，没有改变层级或新增流水线。未触发的LUT密集共享模块保持原区域。','',
        '## 2. 求解结果','',
        '|模块|cells|LUT|FF|DSP|BRAM18|URAM|核心规划范围|实际导出软范围|处理|',
        '|---|---:|---:|---:|---:|---:|---:|---|---|---|']
    labels=dict(expanded='向右扩1列',device_edge_no_expansion='已到X7，保持',not_triggered='未触发')
    for m in mods:
        mid=m['module_id'];e=events[mid]
        lines.append('|'+ '|'.join([mid,*[str(m[k]) for k in ['cells','LUT','FF','DSP','BRAM18','URAM']],region(core['regions'][mid]),region(new['regions'][mid]),labels[e['status']]])+'|')
    lines+=['','模块逻辑来源、top leaf归属和接口组成沿用原始11模块定义，见export/logical_profiles.json；matB与DSP归属未变。','',
        '|触发模块|原URAM需求/容量|扩展后容量|原LUT需求/区域容量|扩展后LUT需求/区域容量|新增CR|','|---|---:|---:|---:|---:|---|']
    for m in mods:
        mid=m['module_id'];e=events[mid]
        if not e['trigger_resources']:continue
        a,b=core['regions'][mid],new['regions'][mid]
        lines.append(f'|{mid}|{m["URAM"]}/{a["capacity"]["URAM"]} = {e["ram_utilization"]["URAM"]:.0%}|{b["capacity"]["URAM"]}|{m["LUT"]/a["capacity"]["LUT"]:.2%}|{m["LUT"]/b["capacity"]["LUT"]:.2%}|'+(', '.join(e['added_crs']) or '无，已到器件边界')+'|')
    lines+=['','X7无URAM，因此URAM预计利用率仍为100%。扩区提供周边逻辑布局余量，不代表URAM数量减少或实际布线通道增加。上述模块自身LUT比例不同于叠加其他模块后的CR总利用率。',
        f'原区域面积之和{core["total_module_crs"]}CR、并集{core["overlap"]["occupied_crs"]}CR；软范围面积之和{new["total_module_crs"]}CR、并集{new["overlap"]["occupied_crs"]}CR，共享{new["overlap"]["overlapping_crs"]}CR。SLR分配完全不变。',
        '对导出软范围另做九类资源比例叠加检查，未把新增区域容量重复分给重叠模块。常量/时钟基础设施和未来fanout helper不计入当前模块预算；规划均值不等于实际物理密度。原方案没有另套历史50%父区域限制，本轮也不添加。','',
        '|资源|核心规划最高CR估计|软范围最高CR估计|沿用上限|','|---|---:|---:|---:|']
    for res,limit in core['limits'].items():lines.append(f'|{res}|{core["overlap"]["maximum_utilization"][res]:.3%}|{new["overlap"]["maximum_utilization"][res]:.3%}|{limit:.0%}|')
    lines+=['','![核心区域与实际导出软区域](figures/regions.png)','',
        '![核心区域及扩展软区域的LUT、URAM、DSP容量比例估计](figures/estimated_utilization.png)','',
        '0%白色并标0，无资源容量为灰色斜线，正利用率使用蓝色档位。下排是假设逻辑按扩展范围容量比例分布的估计，实际placer不保证如此分散。','',
        '## 3. 目标值和覆盖范围','',
        '原规划目标仍为J=D_all+C_fixed+D_dir+32*P_branch，没有归一化；D_all使用超边X/Y/4×SLR跨度，D_dir逐原始sink pin计算X/Y/4×SLR距离，P_branch为单分支max(跨SLR边界数−1,0)²的加权期望。数据权重1，纯控制权重0.25。没有同周期跨多网累计惩罚。',
        '核心区域与核心J保持不变。扩大软范围后，另按同一静态模型重新估算成本，仅用于解释几何变化；这不是新优化目标的搜索结果，也不能因静态距离增加而推断实际布线一定更差。',
        '本轮为确定性导出变换，无MIP incumbent/bound/gap及全局最优声明；原搜索证书仅适用于core_solution.json中的区域。','',
        '|分量|保留的核心区域|扩展软范围的诊断值|','|---|---:|---:|']
    for key,label in [('physical_cost','D_all'),('fixed_partition_cost','C_fixed'),('directed_distance','D_dir'),('directed_slr','有向分支加权SLR边界量'),('branch_square_term','32 P_branch'),('raw_far_pins','跨至少2边界sink pins'),('J','J')]:
        lines.append(f'|{label}|{core["components"][key]:,.4f}|{new["components"][key]:,.4f}|')
    lines+=['','本轮仅改变X方向范围，SLR分布不变：全网远端sink pins仍为17，matA写广播及matB源BRAM广播远端负载仍为0。',
        '覆盖原缓存866740条信号网、2635758个sink pins，其中2631346个具有建模位置；4096个源端为端口的负载和316个接收端口因无位置排除。原缓存的常量及旧CLOCK分类网排除规则不变，包括BUFG驱动基础设施，未新增真实时钟审计。',
        '模块内部连接也计价，同一物理atom内部连接距离为0。资源位置按容量比例独立估计；没有新增STA路径、拥塞反馈或routed坐标读取。模型不预测helper分布、绕行、时钟偏移或局部拥塞。','',
        '## 4. Fanout 处理','',
        '未改写原始网表，未新增driver副本、identity LUT或寄存器；未改变已有fanout算法。BRAM/URAM/FD/LUT处理数量、逐级逻辑和物理fanout、负载集合与功能等价性均未在本轮执行。','',
        '### 原有通用复制策略的验收结果','',
        '本轮不运行复制或Vivado，故无新的fanout验收值，既有实验的通过或超限项不转移为本版结果。新增软范围可供后续实现使用，但不保证复制逻辑的实际分布。','',
        '## 5. 约束验证和物理实现','',
        f'既有适配器已生成`{loc["run"]}/implementation_input/regions.tcl`及membership.tsv。regions.tcl的planned_bounds和planned_regions都写入扩展后的范围，现有bi_apply入口会以IS_SOFT=true建立对应CLOCKREGION Pblock。它是输入数据文件，不是独立完整XDC。',
        'core_solution.json保存原求解区域；export/static_regions.json、solution.json和implementation_input/export/static_regions.json保存实际导出软范围及其诊断成本，避免用旧区域核验新约束。',
        '已用标准Tcl解释器读取实际regions.tcl，并逐项比对11模块边界与CR集合；已验证755385个leaf成员、资源汇总及输入DCP摘要。Vivado内的site/PBLOCK绑定、IS_SOFT实读和区域内外统计需后续实现验证。','',
        '|阶段|WNS/WHS/TNS/THS|route/DRC|区域内外primitive / 实际DSP|','|---|---|---|---|',
        '|place|未执行|未执行|未执行|','|phys_opt|未执行|未执行|未执行|','|route及独立重开|未执行|未执行|未执行|','',
        '最终布线DCP未生成；大小/SHA不适用。当前没有新的实际DSP分布图、最差路径、纵向拥塞或区域内外比例。沿用post-opt/OOC输入，未新增平台I/O约束和时序范围。既有实现DCP保持原样。','',
        '## 6. 已完成测试','',
        f'- 独立资源/CR几何和全网、有向成本复算：{verify["status"]}；核心与扩展两种范围都复算。',
        '- 独立检查严格>80%触发、右侧一列和器件边界：恰好S02/S03/S10改变，S04触发但无可增加的右侧列；其他七模块逐项不变。',
        '- 标准Tcl实际加载regions.tcl，11模块的范围与JSON完全一致；未使用假定的Vivado执行结果。',
        '- membership.tsv与上一版逐字节一致；所有755385个leaf成员、模块资源总量及post-opt DCP绑定通过既有适配器检查。',
        f'- {verify["immutable_input_count"]}个既有输入文件摘要与搜索源快照核验通过。原始core_solution逐字节保留。',
        '- 区域与LUT/URAM/DSP图视觉复核、交付哈希检查另记于delivery_check.json；未进行新的物理或功能等价性试验。','',
        '## 7. 文件','',
        '- [原核心规划](core_solution.json)、[实际软区域与诊断成本](solution.json)、[逐模块扩展记录](padding.json)、[成本对照](comparison.json)。',
        '- [固定模块与逻辑来源](export/modules.json)、[leaf成员](export/leaf_cells.tsv.gz)、[资源](export/module_resources.tsv)、[连接](export/module_connections.tsv)、[端口连接](export/port_connections.tsv)。',
        '- [实现区域输入](implementation_input/regions.tcl)、[实现输入清单](implementation_input/manifest.json)、[独立验证](verification.json)。',
        '- [输入绑定](binding.json)、[服务器位置](location.json)、[运行代码与规则](source/soft_padding.py)、[交付哈希](delivery_manifest.json)。',
        '- 原始DCP、完整membership.tsv及大缓存保留服务器；本地只导入紧凑结果。本轮没有Git提交或发布。']
    (folder/'实验报告.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':report(Path(sys.argv[1]))
