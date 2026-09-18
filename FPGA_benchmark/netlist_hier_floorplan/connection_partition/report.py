"""Render the requested compact module/resource/connection deliverable."""
import argparse
import json
from pathlib import Path


def main(folder):
    data=json.loads((folder/'modules.json').read_text())
    modules=data['modules']; ids=[m['module_id'] for m in modules]
    connections={(p['source'],p['sink']):p for p in data['connections']}
    def number(value): return f'{value:,}'
    def link(name): return f'[{name}](<{folder/name}>)'
    def short(name):
        if name=='TOP': return 'top 直属 leaf cells'
        if 'grp_trisolver_L_double_1024_512_Pipeline_Loop_col' in name: return 'trisolver / Loop_col'
        if name=='grp_trisolver_L_double_1024_512_s_fu_6280': return 'trisolver'
        if name.startswith('grp_kernel_trtrs_0_Pipeline_'): return name.removeprefix('grp_kernel_trtrs_0_Pipeline_')
        if 'matA_' in name: return 'matA_'+name.split('matA_')[-1]
        return name
    lines=['# TRTRS 基于连接关系的粗粒度模块结果','',
        f'已生成 **{len(modules)} 个粗粒度规划模块**，包含全部 {number(data["inventory"]["logic_cells"])} 个逻辑 cells。'
        '每个 cell 只属于一个新模块；原始层级仍保留在成员表中。', '',
        '**本报告使用 P00 等新编号，区别于此前原始层级报告的 M00–M09。**','',
        '## 输入与划分方式','',
        f'- 输入：`{data["input_dcp"]}`。',
        f'- SHA256：`{data["input_sha256"]}`。',
        '- 使用全部独立 leaf cells 与直接连接；原始顶层模块和 top 直属 cells 共同参与划分。',
        f'- KaHyPar 1.3.7，km1目标，初始k={data["initial_k"]}，每块最多{number(data["cell_cap"])}个cells；不要求等大。',
        '- DSP/RAM/CARRY专用级联和LUT/MUX组合保持在同一小单元中。普通/混合网权重1，全部负载均为已识别控制引脚的网权重0.25；时钟和常量不参与聚合。',
        '- 最终允许一个模块跨多个SLR。能够合并且不超过cell上限及全器件资源容量的相连块，按km1收益合并；不施加单SLR资源上限。',
        '- 单SLR原始容量仅用于报告资源下界：LUT432000、FF864000、DSP3072、BRAM18等效1344、URAM320。实际使用几个SLR/clock regions由后续floorplan决定。',
        f'- 运行种子0、1，选择最终加权km1较低的种子 **{data["selected_seed"]}**。','',
        '## 模块资源需求','',
        '**LUT列是网表primitive需求，不是打包后物理LUT占用。LUTMEM包含在LUT中；BRAM36列按BRAM18等效单位除以2表示。**','',
        '| 模块 | cells | LUT | FF | DSP | BRAM36等效 | URAM | top直属cells | SLR资源下界 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for m in modules:
        lines.append('| '+' | '.join([m['module_id'],number(m['cells']),number(m['LUT']),number(m['FF']),number(m['DSP']),f'{m["BRAM18"]/2:g}',number(m['URAM']),number(m['top_direct_cells']),str(m['raw_capacity_min_slrs'])])+' |')
    totals={r:sum(m[r] for m in modules) for r in ('cells','LUT','FF','DSP','BRAM18','URAM','top_direct_cells')}
    lines.append('| **合计** | '+' | '.join([number(totals['cells']),number(totals['LUT']),number(totals['FF']),number(totals['DSP']),f'{totals["BRAM18"]/2:g}',number(totals['URAM']),number(totals['top_direct_cells']),'—'])+' |')
    lines += ['',f'基础设施单列：{number(data["infrastructure"].get("CONSTANT",0))} 个常量 cells、{number(data["infrastructure"].get("CLOCK",0))} 个时钟单元。完整资源表还包含CARRY8、MUXF7、MUXF8和LUTMEM：'+link('module_resources.tsv')+'。',
        'SLR资源下界按FF、DSP、BRAM、URAM原始容量计算；LUT列尚未考虑打包，因此不拿它证明SLR数量下界。该下界也不包含利用率余量、资源位置或布线限制。','',
        '## 模块来自哪些原始逻辑','',
        '| 新模块 | 主要原始归属（cells） | 主要内部子层级（cells） |',
        '|---|---|---|']
    for m in modules:
        owners='；'.join(f'{short(h)}：{number(n)}' for h,n in m['original_owners'][:3])
        nested='；'.join(f'{short(h)}：{number(n)}' for h,n in m['principal_subhierarchies'][:3])
        lines.append(f'| {m["module_id"]} | {owners} | {nested} |')
    lines += ['', '表中只列主要来源，全部原始归属见'+link('module_hierarchy.tsv')+'。原始模块可以被拆分，新的模块也可以同时包含多个原始层级和top直属cells。','',
        '## 模块间连接','',
        '连接保留driver→sink方向。下表一行是驱动模块、一列是负载模块，数值为**唯一bit-net数**。同一条网到达两个目标模块时，会分别出现在两列，矩阵总和不等于全设计唯一cut-net数。','',
        '| 源→目标 | '+' | '.join(ids)+' |',
        '|---|'+'---:|'*len(ids)]
    for source in ids:
        lines.append('| '+source+' | '+' | '.join('—' if source==sink else number(connections.get((source,sink),{}).get('nets',0)) for sink in ids)+' |')
    lines += ['', '连接最强的模块对如下。sink-pin连接数按每个负载引脚计数，用于区分少量高扇出网与大量独立信号。','',
        '| 源 | 目标 | bit-nets | sink-pin连接 | 数据/混合nets | 控制nets |','|---|---|---:|---:|---:|---:|']
    for p in sorted(data['connections'],key=lambda p:-p['sink_pin_connections'])[:16]:
        lines.append('| '+' | '.join([p['source'],p['sink'],number(p['nets']),number(p['sink_pin_connections']),number(p.get('data_nets',0)),number(p.get('control_nets',0))])+' |')
    lines += ['', '完整有向连接表：'+link('module_connections.tsv')+'；顶层I/O单独列于'+link('port_connections.tsv')+'。','',
        '## 当前模块结构的含义','',
        '- P01集中了512个URAM、1024个DSP和4个BRAM36；其URAM需求按原始容量至少需要2个SLR，若下一阶段采用70%容量预算，则至少需要3个SLR。',
        '- P00、P02、P03、P04以LUT/FF为主，各吸收约3.3万个top直属cells；顶层散落逻辑已根据连接与计算逻辑共同模块化。资源类型的差异为后续重叠区域规划提供了输入。',
        '- P04到其他模块共有425200条driver→sink引脚连接，是主要的跨模块负载驱动来源。它到P02只有240条bit-nets，却覆盖114284个负载引脚；两个计数口径需要结合查看。',
        '- 在150000cells上限下，729584个逻辑cells的数量下界是5个模块。本次达到该数量下界，但它仍是当前粒度设置的结果，不意味着设计只有唯一的五模块结构。','',
        '## 连接目标与模块使用','',
        f'- 唯一跨模块bit-nets：**{number(data["metrics"]["cut_nets"])}**。',
        f'- 未加权km1：**{number(data["metrics"]["km1"])}**。',
        f'- 加权cut：**{number(data["metrics"]["weighted_cut"])}**；加权km1：**{number(data["metrics"]["weighted_km1"])}**。',
        '- km1统计一条net所涉及的不同模块数减1；这些数值衡量连接划分，不是实际SLL占用或时序指标。',
        '- floorplan读取模块成员、分资源需求和连接表即可。模块成员互不重复，允许区域是否重叠由下一阶段决定。',
        '- `floorplan_eligible`依据完整模块间连接计算，零模块间连接的对象不应生成区域约束。','',
        '| 候选种子 | 最终模块数 | 加权km1 | 加权cut |', '|---|---:|---:|---:|']
    for c in data['candidates']:
        lines.append(f'| {c["seed"]} | {c["modules"]} | {number(c["weighted_km1"])} | {number(c["weighted_cut"])} |')
    lines += ['', '本次只完成连接模块化，未提取关键路径或routed物理反馈，未运行新的placement/routing；未改写原网表。','',
        '## 文件','',
        '- '+link('leaf_cells.tsv.gz')+'：全部leaf cells、原层级、新模块、分资源需求。',
        '- '+link('module_resources.tsv')+'：模块资源和连接数量汇总。',
        '- '+link('module_connections.tsv')+'：模块间有向连接。',
        '- '+link('modules.json')+'：供后续floorplan读取的紧凑模块描述。',
        '- '+link('remote_run.txt')+'：服务器完整运行目录。','']
    (folder/'模块结果.md').write_text('\n'.join(lines))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path)
    main(parser.parse_args().folder.resolve())
