from pathlib import Path
import csv,hashlib,json,re,sys
from gates import sta,slacks,evaluate
trial=Path(sys.argv[1]);root=trial.parent;config=json.loads((trial/'input.json').read_text());status=json.loads((trial/'status.json').read_text());spec=json.loads((root/config['selection']/'spec.json').read_text())
rejected=(trial/'implementation/REJECTED_BEFORE_ROUTE').exists()
result=dict(status='CANDIDATE_REJECTED' if rejected else 'COMPLETE_WITH_ANNOTATIONS',period_ns=6.7,stages=status['stages'],total_seconds=sum(s['seconds'] for s in status['stages']),timing={},rejected_before_route=rejected,full_route_calls=0 if rejected else 1)
for key,folder in [('before','implementation/before'),('post_place','implementation/post_place'),('post_route','implementation/post_route'),('reopened','reopened')]:
    p=trial/folder/'timing_summary.rpt'
    if p.exists():result['timing'][key]=sta(p)
result['placement_acceptance']=json.loads((trial/'implementation/post_place/acceptance.json').read_text())
result['added_cells']=dict(__import__('collections').Counter(v['config']['ref'] for v in spec['clones'].values()))
result['targets']=len(spec['targets']);result['reused_cells']=len(spec['reuse'])
if not rejected:
    before=trial/'implementation/before';after=trial/'reopened';protected=set(json.loads((root/'protected_originals.json').read_text()))
    final=evaluate(slacks(before/'guard_slacks.tsv'),slacks(after/'guard_slacks.tsv'),sta(before/'timing_summary.rpt'),sta(after/'timing_summary.rpt'),protected)
    result['final_acceptance']=final
    with (after/'fanout_acceptance.tsv').open() as f:fo={r['metric']:r['value'] for r in csv.DictReader(f,delimiter='\t')}
    route=(after/'route_status.rpt').read_text()
    num=lambda pat:int(re.search(pat+r'\.*\s*:\s*(\d+)',route).group(1))
    result['fully_routed']=num('fully routed nets');result['routable']=num('# of routable nets');result['routing_errors']=num('nets with routing errors');result['fanout']=fo
    result['reopen_matches']=result['timing']['post_route']==result['timing']['reopened']
    checks=[]
    for folder in ['implementation/after_edit','implementation/post_place','implementation/post_route','reopened']:
        checks.extend((trial/folder/f).exists() for f in ['joint_structure.tsv','local_structure.tsv','mobility/PASS'])
    result['structural_files_present']=all(checks)
    result['physical_legality']=all((trial/p/'PASS').is_file() for p in
        ['implementation/physical_pre_route', 'implementation/post_route/physical_acceptance', 'reopened/physical_acceptance'])
    gates=final['accepted'] and result['timing']['reopened']['wns']>0 and int(fo['ordinary_ge100'])==0 and result['fully_routed']==result['routable'] and result['routing_errors']==0 and result['reopen_matches'] and all(checks) and result['physical_legality']
    result['status']='COMPLETE' if gates else 'COMPLETE_WITH_ANNOTATIONS'
    if not result['physical_legality'] or result['fully_routed']!=result['routable'] or result['routing_errors']:
        result['status']='STOPPED_WITH_EVIDENCE'
    dcp=trial/'implementation/post_route.dcp';h=hashlib.sha256()
    with dcp.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    result.update(dcp=str(dcp),dcp_sha256=h.hexdigest())
result['verification_runtime'] = []
for runtime in [trial/'implementation/verification_runtime.tsv', trial/'reopened/verification_runtime.tsv']:
    if runtime.exists():
        with runtime.open() as f:
            for row in csv.DictReader(f, delimiter='\t'):
                result['verification_runtime'].append(dict(scope=runtime.parent.name, phase=row['phase'], seconds=float(row['seconds']), counters=row['counters']))
result['memory_admissions'] = []
for admission in sorted(trial.rglob('memory_admission_*.json')):
    result['memory_admissions'].append(json.loads(admission.read_text()))
result['memory_wait_seconds'] = sum(x.get('wait_seconds',0) for x in result['memory_admissions'])
result['comparison_note'] = 'Same input/selection/period as reference; concurrent CPU load and memory waits must be separated from verification speedup.'
(trial/'result.json').write_text(json.dumps(result,indent=2)+'\n');report=trial/'report';report.mkdir(exist_ok=True)
time_rows='\n'.join(f"|{k}|{v['wns']:+.3f}|{v['tns']:.3f}|{v['setup_failing']}|{v['whs']:+.3f}|" for k,v in result['timing'].items())
stage_rows='\n'.join(f"|{x['name']}|{x['seconds']:.1f}|" for x in status['stages'])
text=f'''# GETRF 6.7ns 联合输入逻辑与位置优化

状态：**{result['status']}**。本报告区分程序执行、结构核验与数值效果。

## 输入与范围

从上一轮trial02的已布线DCP开始；周期6.7ns、原22模块floorplan和fanout<100保持。输入路径及SHA256见[输入记录](../input.json)。原结果与公共流程保留，没有新增流水级、FF或前端修改。

## 求解结果

本轮使用完整有界输入逻辑检查；完整MUX组作为规划单元。单SLR RAM输入组优先留在源端，混合来源组向目标FF侧收敛，末组与FF同SLR。全输入源位置参与规划，不把D/Q两段时序相加。当前候选覆盖{result['targets']}个端点，复用{result['reused_cells']}个已拥有的末级cell。该候选为首批D输入优化，其他端点保留明确覆盖/延后记录，未声称全局最优。

## 目标值和覆盖范围

同时检查目标与原FF D/CE/复位、Q输出可达端点、修改上游的其他消费者及全局最差1000端点。保留上一轮43个原FF的正时序保护基准。布局候选必须通过原分支保护与WNS/TNS门限后才布线。布局拒绝：{rejected}；[布局验收](../implementation/post_place/acceptance.json)。

## Fanout处理

新增原语计数：`{result['added_cells']}`。并行复制现有LUT解决新增上游负载，不插入额外组合级。完整预算由离线与原生读回独立比对；[预算](../implementation/projected_fanout.tsv)。继承的区域树连接证书仅按已证明等价的变化更新，仍执行完整覆盖和物理检查。

## 约束验证和物理实现

|阶段|WNS/ns|TNS/ns|setup端点|WHS/ns|
|---|---:|---:|---:|---:|
{time_rows}

新增cell使用整SLR范围，不固定LOC/BEL；原模块范围与成员不变。详见[修改后结构](../implementation/after_edit/joint_structure.tsv)、[布局后结构](../implementation/post_place/joint_structure.tsv)。最终DCP：`{result.get('dcp','候选在布线前被拒绝，未生成新的routed DCP')}`。

## 已完成测试

图规划与时序门限单元测试、原生LUT/MUX/常量/FF控制连接测试及小型DCP独立重开在运行前完成。真实case保留全部继承结构、区域、mobility与最终独立重开。原语与精确连接证明不等于全设计形式验证。[结果JSON](../result.json)。

## 耗时、风险与后续

|阶段|秒|
|---|---:|
{stage_rows}

实现及独立验收总{result['total_seconds']:.1f}秒，完整route_design调用{result['full_route_calls']}次；检查/规划/原生测试耗时另记，不混入纯实现耗时。数值未达标保留结果并标注，未自动重复布线。没有恢复定时监控。只读缓存的分阶段实测时间与内存准入等待时间见结果JSON；并行CPU竞争及等待不应归因于脚本本身。
'''
(report/'实验报告.md').write_text(text)
print(json.dumps({k:v for k,v in result.items() if k not in ['placement_acceptance','final_acceptance']}))
