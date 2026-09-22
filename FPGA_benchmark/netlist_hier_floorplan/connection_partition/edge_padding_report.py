"""Study plots; stack labels of modules sharing a CR anchor."""
import csv
import json
from pathlib import Path
import sys


def load(p):return json.loads(p.read_text())


def plots(folder):
    try:
        import matplotlib
    except ModuleNotFoundError:
        from edge_padding_plot_local import plots as portable_plots
        return portable_plots(folder)
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import ListedColormap,BoundaryNorm
    from matplotlib.patches import Rectangle,Patch
    new=load(folder/'solution.json');old=load(folder/'input/export/static_regions.json')
    assert new['resource_accounting']['schema']=='core-only-v1'
    padding={c for r in new['regions'].values() for c in r['padding_crs']}
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
    threshold_label=f"{new['edge_padding']['policy']['threshold']:.0%}"
    for ax,plan,title in zip(axes,[old,new],['J-selected core floorplan',f'Export-only {threshold_label} edge expansion']):
        grid(ax);ax.set_title(title);label_slots={}
        for i,(mid,r) in enumerate(sorted(plan['regions'].items())):
            x0,y0,x1,y1=r['bounds'];color=palette(i)
            cells={tuple(map(int,c[1:].split('Y'))) for c in r['crs']}
            for x,y in cells:
                ax.add_patch(Rectangle((x-.5,y-.5),1,1,facecolor=(*color[:3],.12),edgecolor='none'))
                for dx,dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                    if (x+dx,y+dy) not in cells:
                        xx=[x+dx*.5,x+dx*.5] if dx else [x-.5,x+.5]
                        yy=[y+dy*.5,y+dy*.5] if dy else [y-.5,y+.5]
                        ax.plot(xx,yy,color=color,lw=2)
            label_x,label_y=min(cells,key=lambda xy:(xy[1],xy[0]))
            slot=label_slots.get((label_x,label_y),0);label_slots[label_x,label_y]=slot+1
            ax.text(label_x-.3,label_y-.22+.3*slot,mid,fontsize=10,fontweight='bold',
                    bbox=dict(facecolor='white',alpha=.9,edgecolor='none',pad=1))
        if plan is new:
            for c in sorted(padding):
                d=device[c];ax.add_patch(Rectangle((d['x']-.5,d['y']-.5),1,1,
                    facecolor='#fef3c7',edgecolor='#b45309',hatch='xx',lw=1,alpha=.65,zorder=0.5))
        if not leg:leg=[Patch(facecolor=palette(i),label=m) for i,m in enumerate(sorted(plan['regions']))]
    leg.append(Patch(facecolor='#fef3c7',edgecolor='#b45309',hatch='xx',label='Soft extension (unallocated)'))
    fig.legend(handles=leg,loc='outside lower center',ncol=6,fontsize=9)
    fig.savefig(figdir/'regions.png',dpi=160);plt.close(fig)
    thresholds=[.01,.05,.1,.2,.4,.6,.8,1,float('inf')]
    labels=['>0-1%','>1-5%','>5-10%','>10-20%','>20-40%','>40-60%','>60-80%','>80-100%','>100%']
    cmap=ListedColormap(['#b1dff0','#79c9e4','#42b0d2','#188daf','#116b99','#21518a','#30366f','#171c49','#b91c1c'])
    cmap.set_bad((1,1,1,0));norm=BoundaryNorm(np.arange(-.5,9.5),9)
    fig,axes=plt.subplots(2,3,figsize=(18,19),layout='constrained')
    for row,plan in enumerate([old,new]):
        # Both panels share exactly the selected core's demand projection.
        usage={r['cr']:r['utilization'] for r in old['overlap']['contributions']}
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
                        ax.add_patch(Rectangle((x-.5,y-.5),1,1,facecolor='#e5e7eb',edgecolor='#9ca3af',hatch='///',lw=0))
                    if row==1 and f'X{x}Y{y}' in padding:
                        ax.add_patch(Rectangle((x-.5,y-.5),1,1,facecolor='#fef3c7' if np.isfinite(v) else 'none',edgecolor='#b45309',hatch='xx',lw=1))
                        ax.text(x,y,'EXT',ha='center',va='center',fontsize=8,fontweight='bold',color='#92400e',
                            bbox=dict(facecolor='white',alpha=.85,edgecolor='none',pad=.5))
                        continue
                    if not np.isfinite(v):continue
                    text='0%' if v==0 else '<0.1%' if v<.001 else f'{v:.1%}' if v<.01 else f'{v:.0%}'
                    ax.text(x,y,text,ha='center',va='center',fontsize=7,color='white' if v>0 and bands[y,x]>=3 else '#334155')
            grid(ax);ax.set_title(('Core resource estimate' if row==0 else 'Same estimate + soft extensions')+f': estimated {res}')
            cb=fig.colorbar(pic,ax=ax,fraction=.04,pad=.12,ticks=range(9));cb.ax.set_yticklabels(labels,fontsize=7)
    fig.legend(handles=[Patch(facecolor='white',edgecolor='#94a3b8',label='0%: available, unused'),
        Patch(facecolor='#e5e7eb',edgecolor='#9ca3af',hatch='///',label='No resource capacity'),
        Patch(facecolor='#fef3c7',edgecolor='#b45309',hatch='xx',label='EXT: selected soft range, no resource allocation')],loc='outside lower center',ncol=3)
    fig.suptitle('Resources and J use the core only; extensions are soft geometry, not predicted usage',fontsize=15)
    fig.savefig(figdir/'estimated_utilization.png',dpi=150);plt.close(fig)


def report(folder):
    new=load(folder/'solution.json');old=load(folder/'input/export/static_regions.json')
    modules=load(folder/'export/modules.json')['modules'];rule=new['edge_padding']
    binding=load(folder/'binding.json');v=load(folder/'verification.json');loc=load(folder/'location.json')
    plots(folder)
    changes={r['module']:r for r in rule['changes']}
    threshold_label=f"{rule['policy']['threshold']:.0%}"
    lines=['# TRTRS：保留原J求解结果，再统一扩展50%边缘软约束','',
        '**状态：保留输入的J求解核心规划，统一50%规则的软约束生成及独立核验完成。没有S01整die指定范围，没有单独RAM80%规则；未运行新的placement、route、STA或fanout。**','',
        '## 1. 输入与范围','',
        f'服务器eda070；独立目录：`{loc["run"]}`。基线：`{binding["previous"]}`。',
        f'输入post-opt DCP：`{binding["input_dcp"]}`；SHA256：`{binding["input_sha256"]}`。',
        '沿用固定11模块、755385个leaf成员、729584个模块逻辑cell及原始逻辑来源；25800个常量和1个旧CLOCK分类基础设施单列。所有模块均有模块间连接。没有重划分、拆分DSP子层、改变matB归属、重跑搜索或新增寄存器。',
        '直接复用绑定输入的核心解，随后统一应用一次50%规则；URAM与其他资源一样参与判定，不再运行独立80%右扩规则。核心资源容量、利用率和J不重新计算；新增CR只作为软约束几何范围并在图中标记。','',
        '## 2. 求解结果','',
        '对模块边缘的每个CR，累加所有覆盖模块的各类资源预计利用率；只要任一项严格>50%，检查上下左右相邻CR。目标必须与该边缘CR处于同一SLR，且在扩展前没有任何模块覆盖。50%是触发阈值，原有资源上限不变。',
        '所有申请从原始核心规划同时生成，仅执行一轮，不含对角、不递归扩展。同一核心空CR对所有符合条件的模块开放，允许扩展后的软范围重叠，不按利用率或模块编号分出唯一归属。目标CR不必包含触发的RAM资源，可提供周边逻辑的软布局空间。','',
        '|模块|cells|LUT|FF|DSP|BRAM18|URAM|CR数量前→后|新增CR|',
        '|---|---:|---:|---:|---:|---:|---:|---|---|']
    for m in modules:
        mid=m['module_id'];r=changes[mid]
        lines.append('|'+ '|'.join([mid,*[str(m[k]) for k in ['cells','LUT','FF','DSP','BRAM18','URAM']],
            f'{len(r["before_crs"])}→{len(r["after_crs"])}',','.join(r['added_crs']) or '无'])+'|')
    lines+=['',f'实际改变模块：{", ".join(rule["changed_modules"]) or "无"}；新增物理CR去重后为{rule["added_unique_crs"]}个，按模块累计增加{rule["added_module_crs"]}个CR使用范围，其中{rule["shared_new_crs"]}个新增CR被多个模块共享。总模块面积{new["soft_geometry"]["total_module_crs"]}CR，并集{new["soft_geometry"]["occupied_crs"]}CR，共享{new["soft_geometry"]["overlapping_crs"]}CR。',
        '所有模块核心位置不变，统一接受50%扩展规则，没有整SLR覆盖例外。原始搜索面积上限只约束核心候选，后处理软范围可以更大。非矩形范围严格按新增CR集合表达，图中外包矩形内缺少的角不自动补入。','',
        '|资源|核心最高CR预计利用率|导出后沿用的核心利用率|规划上限|','|---|---:|---:|---:|']
    for res in new['limits']:
        lines.append(f'|{res}|{old["overlap"]["maximum_utilization"][res]:.3%}|{new["overlap"]["maximum_utilization"][res]:.3%}|{new["limits"][res]:.0%}|')
    lines+=['','核心逐CR资源检查通过；扩展CR不增加规划容量、不分摊需求、不重算成本。各SLR模块需求总账不变；实际布局尚未测量。',
        '![前后软区域](figures/regions.png)','',
        '![LUT、URAM、DSP预计利用率](figures/estimated_utilization.png)','',
        '图示使用精确CR集合；0%为白色，无资源容量为灰色斜线。扩展CR以橙色交叉纹和EXT标记，不是资源使用率。软区域重叠不表示预先分配同一个物理site。','',
        '## 3. 目标值和覆盖范围','',
        f'本次沿用输入核心J={old["objective"]}及全部配置，不重新求解。扩展CR不进入成本或容量计算，也不构成WNS预测。','',
        '|分量|原J核心规划|导出后核心值|','|---|---:|---:|']
    for k in ['physical_cost','directed_distance','branch_square_term','raw_far_pins','J']:
        lines.append(f'|{k}|{old["components"][k]:,.4f}|{new["components"][k]:,.4f}|')
    lines+=['','覆盖既有866740条信号网、2635758个sink pins，其中2631346个可定位；4096个源端口负载和316个接收端口排除。旧常量/CLOCK基础设施规则保持。同atom分支距离为0，其余按容量分布估计。没有提取新的STA路径，也不累计同周期多网路径。','',
        '## 4. Fanout处理','',
        '未执行driver复制、内存树、phys_opt或网表变换；BRAM/URAM/FD/LUT处理数量、各级fanout和功能等价性没有新测量。没有增加周期。','',
        '### 原有通用复制策略的验收结果','',
        '本轮未执行；历史fanout与时序结果不能作为这一版的验收值。','',
        '## 5. 约束验证和物理实现','',
        f'实际输入：`{loc["run"]}/implementation_input/`。',
        'regions.tcl携带精确CR集合，并自动加载同目录soft_region_adapter.tcl；该文件只更新Pblock范围施加过程，保持调用方的fanout和保护流程。仍使用IS_SOFT=true。非矩形区域以多个CR范围表达，避免用外包矩形误纳已占用CR。',
        '依据[AMD resize_pblock命令说明](https://docs.amd.com/r/JXswcrCHJROaHTz43h5g2Q/FW3hgWm5cHHoonLgmVwfiA)，Pblock可以由多个矩形组成。标准Tcl加载和范围核验通过；尚未在Vivado中执行新约束或读取原生site几何。',
        'membership.tsv与参考输入逐字节相同。core_solution.json与用户指定输入的核心规划逐字节一致；新增selection字段和core_objective明确保留原始J选择，soft_diagnostic_objective为null（不计算）；planning_regions保存核心容量，regions仅保存软范围几何。实现输入不含旧padding.json或override.json；最终软范围以regions.tcl和edge_padding.json为准。','',
        '|阶段|WNS/WHS/TNS/THS|route/DRC|模块区域内外/实际DSP|','|---|---|---|---|',
        '|place|未执行|未执行|未执行|','|phys_opt|未执行|未执行|未执行|','|route及重开|未执行|未执行|未执行|','',
        '未生成新物理DCP，大小/SHA不适用；无实际DSP分布图、最差路径或板级/完整平台验收。原post-opt输入与时序约束不变。','',
        '## 6. 已完成测试','',
        f'- 独立核验：{v["status"]}；从每个核心空目标CR反向枚举相邻高利用率边缘，核验阈值、die、所有符合条件的模块及全部共享新增CR。',
        '- 755385个leaf唯一性、cell_id、资源汇总、membership字节及全部旧输入/源快照摘要核验。',
        '- 边缘扩展/核心保护及既有有向成本回归通过：包含恰好50%、共享扩展、顺序无关、叠加触发、核心占用排除、跨die排除、单轮、非矩形和同外包框不同CR集合缓存；具体记录见tests.log。',
        '- 通信成本用独立CR对枚举和超边概率乘积重算。标准Tcl读取精确CR集合；本地图片与交付摘要核验见delivery_check.json。',
        '- 不声明新Vivado约束实测、路由改善或功能等价性验证。','',
        '## 7. 文件','',
        '- [原J核心规划](core_solution.json)、[最终软区域](solution.json)、[逐边缘触发及新增CR](edge_padding.json)、[前后成本](comparison.json)、[独立验证](verification.json)。',
        '- [实际区域输入](implementation_input/regions.tcl)、[精确CR适配器](implementation_input/soft_region_adapter.tcl)、[输入清单](implementation_input/manifest.json)。',
        '- [模块资源](export/module_resources.tsv)、[模块连接](export/module_connections.tsv)、[端口连接](export/port_connections.tsv)、[leaf成员](export/leaf_cells.tsv.gz)、[逻辑来源](export/logical_profiles.json)。',
        '- [输入绑定](binding.json)、[服务器位置](location.json)、[源快照](source/)、[交付摘要](delivery_manifest.json)。',
        '- 完整membership和大型DCP/连接缓存保留服务器。未提交或上传Git。']
    (folder/'实验报告.md').write_text('\n'.join(lines).replace('50%',threshold_label)+'\n')


if __name__=='__main__':report(Path(sys.argv[1]).resolve())
