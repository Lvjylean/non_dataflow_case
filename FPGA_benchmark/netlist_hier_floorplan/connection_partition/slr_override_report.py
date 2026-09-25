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
    for ax,plan,title in zip(axes,[old,new],['Previous RAM-padded soft regions','S01 soft region = whole SLR2']):
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
            grid(ax);ax.set_title(('Previous' if row==0 else 'Override diagnostic')+f': estimated {res}')
            cb=fig.colorbar(pic,ax=ax,fraction=.04,pad=.12,ticks=range(9));cb.ax.set_yticklabels(labels,fontsize=7)
    fig.legend(handles=[Patch(facecolor='white',edgecolor='#94a3b8',label='0%: available, unused'),
        Patch(facecolor='#e5e7eb',edgecolor='#9ca3af',hatch='///',label='No resource capacity')],loc='outside lower center',ncol=2)
    fig.suptitle('Uniform-spread diagnostic only; no new placement or routing',fontsize=15)
    fig.savefig(figdir/'estimated_utilization.png',dpi=150);plt.close(fig)

def report(folder):
    new=load(folder/'solution.json');old=load(folder/'input/export/static_regions.json');meta=load(folder/'export/modules.json')
    binding=load(folder/'binding.json');verify=load(folder/'verification.json');loc=load(folder/'location.json')
    plots(folder)
    def region(r):
        x0,y0,x1,y1=r['bounds'];return ','.join('SLR'+str(s) for s in r['slrs'])+f' / X{x0}Y{y0}:X{x1}Y{y1}'
    lines=['# TRTRS：S01使用整个SLR2的软Pblock对照版','',
        '**状态：实验输入生成并核验完成。只有S01软区域改变，其他10模块保持RAM右扩版本。未执行新的placement、route、STA或fanout。旧均摊占用模型的局部超限作为诊断保留，不标为原优化模型可行解。**','',
        '## 1. 输入与范围','',f'服务器：eda070。独立目录：`{loc["run"]}`。',
        f'基线：`{binding["previous"]}/implementation_input/`。',
        f'输入post-opt DCP：`{binding["input_dcp"]}`；SHA256：`{binding["input_sha256"]}`。',
        '保留11个S00–S10模块、755385个leaf成员、原始逻辑来源、资源需求和连接。其中729584个模块逻辑cell包含133097个top直属逻辑cell；25800个常量和1个旧CLOCK分类基础设施仍单列。所有11模块有模块间连接，无孤立模块排除。',
        '明确执行用户指定的软范围：S01从SLR3的X4Y12:X6Y13改为SLR2全部32个CR，即X0Y8:X7Y11，IS_SOFT=true。此规则在上轮RAM>80%右扩规则之后应用；S02/S03/S10保留X7扩展，S04保持原范围。',
        '没有重新partition、移动其他模块的规划区域、拆分DSP子层、改变matB归属或插入寄存器。S01不含URAM/BRAM，只有其允许布局范围变宽。原核心规划和上轮软区域单独保存，不伪装成重新搜索结果。','',
        '## 2. 求解结果','',
        '|模块|cells|LUT|FF|DSP|BRAM18|URAM|原软范围|本版软范围|','|---|---:|---:|---:|---:|---:|---:|---|---|']
    for m in meta['modules']:
        mid=m['module_id'];lines.append('|'+ '|'.join([mid,*[str(m[k]) for k in ['cells','LUT','FF','DSP','BRAM18','URAM']],region(old['regions'][mid]),region(new['regions'][mid])])+'|')
    lines+=['',f'软区域面积之和{new["total_module_crs"]}CR，并集{new["overlap"]["occupied_crs"]}CR，共享{new["overlap"]["overlapping_crs"]}CR。共享范围不表示同一site被预先分配给多个cell，实际合法位置由Vivado选择。',
        'S01原始主要逻辑来源及所有模块的详细层级贡献保持export/logical_profiles.json中的定义，编号不表示新增RTL层级。','',
        '|SLR2资源|总容量|含S01后的模块需求|总利用率|原规划预算|','|---|---:|---:|---:|---:|']
    budget=new['slr_resource_budgets']['2']
    for r in ['LUT','FF','DSP','BRAM18','URAM','LUTMEM','CARRY8','MUXF7','MUXF8']:
        lines.append(f'|{r}|{budget["capacity"][r]:,}|{budget["demand"][r]:,}|{budget["utilization"][r]:.3%}|{new["limits"][r]:.0%}|')
    lines+=['','SLR2的原模块LUT需求241612；按70%预算剩60788，S01需求56234，加入后预算余量4554。这里是原始模块资源账，未来复制/helper和全局基础设施尚未附加，不能代替实际布局布线验收。',
        f'若仍将S01按整个SLR2的总容量比例分摊，局部LUT诊断峰值为{new["overlap"]["maximum_utilization"]["LUT"]:.3%}，超过旧70%规划线。该假设并不表达用户希望的“优先使用剩余空间”，因此本版允许导出并标记uniform_overlap_pass=false；没有修改原始70%/URAM100%规则，也没有给出逐CR占用通过证书。',
        '现有适配器创建软Pblock，后续优化允许越界。没有给S01设定硬SLR约束，也不保证全部cell最终留在SLR2。','',
        '![上轮与本版软范围](figures/regions.png)','',
        '![均摊假设下的LUT、URAM、DSP诊断图](figures/estimated_utilization.png)','',
        '资源图仅说明旧容量比例分布模型会怎样计价，不代表Vivado最终布局。0%为白色标0；无资源为灰色斜线；所有正值分档显示。','',
        '## 3. 目标值和覆盖范围','',
        '没有执行新的优化，incumbent/bound/gap不适用。原目标J=D_all+C_fixed+D_dir+32P_branch及参数保持不变，只对实际导出范围重新做均摊模型诊断。SLR距离系数4，数据网权重1、纯控制0.25，不归一化、不累计同周期多网路径。',
        '本版状态为soft_override_ready，而不是feasible。目标值只能作为相同代理模型的对照，不能解释为真实剩余空间布局的成本或全局最优解。','',
        '|诊断分量|上轮软范围|S01整个SLR2|','|---|---:|---:|']
    for k,label in [('physical_cost','D_all'),('directed_distance','D_dir'),('directed_slr','有向加权跨界量'),('branch_square_term','32P_branch'),('raw_far_pins','跨至少2边界sink pins'),('J','诊断J')]:
        lines.append(f'|{label}|{old["components"][k]:,.4f}|{new["components"][k]:,.4f}|')
    lines+=['','覆盖原缓存866740条信号网、2635758个sink pins，其中2631346个可定位；4096个源端口负载和316个接收端口排除。常量和旧CLOCK/BUFG基础设施排除规则不变，未新增真实时钟审计。模块内部连接计价，同atom内部距离为0。',
        'S01采用整个SLR2后，本版没有使用SLR3的软区域；但这仅是初始布局引导。未提取新的STA路径或拥塞反馈，也未证明新的WNS/SLL改善。','',
        '## 4. Fanout处理','',
        '本轮没有driver复制、memory identity树或原生fanout优化，没有增加流水线周期。BRAM/URAM/FD/LUT处理数量、各级逻辑/物理fanout、负载保持、INIT和功能等价性均未在本轮运行。','',
        '### 原有通用复制策略的验收结果','',
        '未执行。后续可选择既有fanout流程，但不把历史结果转写为本版验收值。','',
        '## 5. 约束验证和物理实现','',
        f'实际实验输入：`{loc["run"]}/implementation_input/`。已生成最终regions.tcl和与基线逐字节相同的membership.tsv。',
        '标准Tcl解释器加载regions.tcl后，S01的planned_bounds为{0 8 7 11}，planned_regions精确包含SLR2的32个CR；其余10模块范围与基线相同。既有adapter.tcl的bi_apply使用CLOCKREGION范围和IS_SOFT=true；该参考代码快照已保存。',
        '完整输入清单已重建，包含实际export/static_regions.json、override.json与区域数据。core_solution.json保留原优化结果；上轮padding.json保留为历史规则记录，最终约束以regions.tcl及override.json为准。','',
        '|阶段|时序WNS/WHS/TNS/THS|route/DRC|区域内外及实际DSP|','|---|---|---|---|',
        '|place|未执行|未执行|未执行|','|phys_opt|未执行|未执行|未执行|','|route及重开|未执行|未执行|未执行|','',
        '没有新的最终DCP，大小/SHA不适用；没有实际DSP分布图、site几何实读或最差路径。输入DCP/OOC范围和原时序约束保持，未新增平台I/O约束，未执行板级或完整平台时序验收。','',
        '## 6. 已完成测试','',
        f'- 独立复算、几何和成员核验：{verify["status"]}；只改变S01，其他10模块逐项一致。',
        '- 755385个leaf唯一性、原始cell_id、模块资源汇总重新核验；membership.tsv与基线逐字节相同。',
        '- 标准Tcl加载最终regions.tcl，CR集合与JSON一致；各SLR总资源预算通过。旧均摊模型局部超限明确保留，不作通过声明。',
        f'- {verify["immutable_input_count"]}个既有输入文件、post-opt DCP、源快照和实现输入清单摘要核验通过。',
        '- 有向分支以CR对枚举、超边以概率乘积独立重算；未复用优化器评分方法。图像及本地交付检查见delivery_check.json。',
        '- 无新的Vivado、fanout改写或功能等价性测试。','',
        '## 7. 文件','',
        '- [最终软范围与诊断](solution.json)、[S01覆盖规则](override.json)、[前后对照](comparison.json)、[独立核验](verification.json)。',
        '- [实际区域输入](implementation_input/regions.tcl)、[输入清单](implementation_input/manifest.json)、[原核心规划](core_solution.json)。',
        '- [模块](export/modules.json)、[leaf成员](export/leaf_cells.tsv.gz)、[资源](export/module_resources.tsv)、[连接](export/module_connections.tsv)、[端口连接](export/port_connections.tsv)。',
        '- [输入绑定](binding.json)、[服务器位置](location.json)、[源快照](source/)、[交付摘要](delivery_manifest.json)。',
        '- 完整membership和DCP保留服务器；没有Git提交或发布。']
    (folder/'实验报告.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':report(Path(sys.argv[1]))
