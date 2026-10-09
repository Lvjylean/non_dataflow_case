"""Generate the seven-section report from measured artifacts, including unmet gates."""
from pathlib import Path
import csv
import hashlib
import html
import importlib.util
import json
import re
import os

ROOT = Path(os.environ['COMPILEFAST_RUN_ROOT'])
CODE = Path(__file__).resolve().parent
loc = json.loads((ROOT/'location.json').read_text())
state = json.loads((ROOT/'status.json').read_text())
case_name = loc.get('case_name', 'FPGA backend')
reference_seconds = loc.get('reference_total_s')
has_reference = reference_seconds is not None
out = ROOT/'report'
out.mkdir(exist_ok=True)
fig = out/'figures'
fig.mkdir(exist_ok=True)


def read(path):
    p = ROOT/path
    return p.read_text(errors='replace') if p.exists() else ''


def rows(path):
    text = read(path)
    return list(csv.DictReader(text.splitlines(), delimiter='\t')) if text else []


def duration(seconds):
    v = round(seconds)
    return f'{v//3600}:{v%3600//60:02d}:{v%60:02d}'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8388608),b''):
            h.update(b)
    return h.hexdigest()


spec = importlib.util.spec_from_file_location('timing_parser', CODE/'code/regional/run_case.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
clock_rows = rows('seed/clock.tsv')
clock_name = clock_rows[0]['clock'] if clock_rows else loc.get('clock_port', 'ap_clk')
timing = {}
for stage, path in [('seed','seed/seed_place'),('base','base/pre_route'),
        ('post_place','generic/implementation/post_place'),('post_route','generic/implementation/post_route'),
        ('reopened','generic/reopened')]:
    p = ROOT/path/'timing_summary.rpt'
    if p.exists():
        timing[stage] = parser.timing(p)
        clock = re.search(r'^'+re.escape(clock_name)+r'\s+\{[^}]*\}\s+([\d.]+)',p.read_text(),re.M)
        timing[stage]['clock_period_ns'] = float(clock[1]) if clock else None
fanout = {r['metric']:int(r['value']) for r in rows('generic/reopened/fanout_acceptance.tsv')}
unsupported = rows('generic/reopened/fanout_final/scan_summary.tsv')
route = read('generic/reopened/route_status.rpt')
fully = re.search(r'# of fully routed nets[^:]*:\s*(\d+)',route)
routable = re.search(r'# of routable nets[^:]*:\s*(\d+)',route)
errors = re.search(r'# of nets with routing errors[^:]*:\s*(\d+)',route)
markers = [ROOT/'generic'/p/'structural_pass.txt' for p in
           ['implementation/after_edit','implementation/post_place','implementation/post_route','reopened']]
regional_markers = [ROOT/'generic'/p/'regional_structure.tsv' for p in
           ['implementation/after_edit','implementation/post_place','implementation/post_route','reopened']]
structure_ok = all(p.is_file() and p.read_text().startswith('PASS') for p in markers)
structure_ok = structure_ok and all(p.is_file() for p in regional_markers)
mobility_markers = [ROOT/'generic'/p/'PASS' for p in ['implementation/mobility_after_edit','implementation/post_place/mobility','implementation/post_route/mobility','reopened/mobility']]
mobility_ok = all(p.is_file() and p.read_text().startswith('PASS') for p in mobility_markers)
local_stages = ['implementation/after_edit','implementation/post_place','implementation/post_route','reopened']
local_checks = {stage:{r['check']:r['value'] for r in rows('generic/'+stage+'/local_structure.tsv')}
                for stage in local_stages}
local_ok = all(all(checks.get(k)=='PASS' for k in
    ['exact_connectivity','primitive_config_and_inputs','original_floorplan','copy_slr_and_mobility'])
    for checks in local_checks.values())
local_timing = rows('generic/reopened/local_timing_groups.tsv')
replicas = rows('generic/implementation/replicas.tsv')
structure_ok = structure_ok and mobility_ok and local_ok
routed_ok = bool(fully and routable and errors and fully[1] == routable[1] and int(errors[1]) == 0)
physical_markers = [ROOT/'generic'/p/'PASS' for p in
    ['implementation/physical_pre_route', 'implementation/post_route/physical_acceptance',
     'reopened/physical_acceptance']]
physical_ok = all(p.is_file() for p in physical_markers)
timing_ok = all(s in timing and timing[s]['clock_period_ns'] is not None
    and abs(timing[s]['clock_period_ns']-loc['clock_period_ns']) < 1e-6 and timing[s]['wns_ns'] > 0
    and timing[s]['tns_ns'] == 0 and timing[s]['setup_failing'] == 0 and timing[s]['hold_failing'] == 0
    for s in ['post_route','reopened'])
fanout_ok = fanout.get('ordinary_ge100') == 0 and bool(unsupported) and int(unsupported[0]['unsupported_ordinary']) == 0
complete = state['status'] == 'COMPLETE_REVIEW_CRITERIA'
joint_path=ROOT/'generic/implementation/joint_placed/acceptance.json'
joint_acceptance=json.loads(joint_path.read_text()) if joint_path.exists() else {}
joint_ok=joint_acceptance.get('accepted') is True and (joint_path.parent/'PASS').is_file()
joint_candidates_path=ROOT/'generic/implementation/joint_candidates.json'
joint_candidates=json.loads(joint_candidates_path.read_text()) if joint_candidates_path.exists() else {}
timing_extraction=[]
for stage in ['joint_before','joint_placed']:
    directory=ROOT/'generic/implementation'/stage
    calls={}
    for path in directory.glob('slacks.tsv*.runtime.tsv'):
        for row in csv.DictReader(path.open(),delimiter='\t'):
            bucket=calls.setdefault(row['phase'],dict(calls=0,seconds=0.0,errors=0))
            bucket['calls']+=1;bucket['seconds']+=int(row['elapsed_us'])/1e6
            bucket['errors']+=int(row['returncode']!='0')
    if calls:
        timing_extraction.append(dict(stage=stage,calls=calls,measured_call_seconds=sum(x['seconds'] for x in calls.values()),
            coverage=rows(f'generic/implementation/{stage}/slacks.tsv.coverage.tsv')))
elapsed = state['compile_seconds']
speed_ok = complete and elapsed < reference_seconds if has_reference else None
sll_enabled = (ROOT/'sll_input.json').exists()
sll_removed = (ROOT/'sll_reservation/removed.tsv').is_file()
sll_usage = rows('generic/reopened/sll_usage/routed_sll_bundles.tsv')
sll_ok = (sll_removed and len(sll_usage) == 48) if sll_enabled else True
success = complete and timing_ok and fanout_ok and structure_ok and routed_ok and physical_ok and joint_ok and state['input_unchanged'] and sll_ok
result_status = ('SUCCESS' if success else ('COMPLETE_WITH_ANNOTATIONS' if complete else state['status']))
if complete and not (physical_ok and routed_ok and joint_ok):
    result_status = 'STOPPED_WITH_EVIDENCE'
result = dict(status=result_status,
    compile_scope=loc.get('compile_scope','complete_flow'),
    placed_wns_policy=loc.get('joint_wns_policy','nonworse'),
    timing_extraction=dict(mode=loc.get('timing_extraction','reference'),stages=timing_extraction),
    historical_comparison_only=has_reference, compile_seconds=elapsed, historical_seconds=reference_seconds,
    saved_seconds=reference_seconds-elapsed if complete and has_reference else None,
    gates=dict(compile_time_reduced=speed_ok,timing_positive=timing_ok,fanout=fanout_ok,
               structural=structure_ok,mobility=mobility_ok,local_replication=local_ok,fully_routed=routed_ok,
               physical_legality=physical_ok,joint_placed_timing=joint_ok,input_unchanged=state['input_unchanged']),
    joint_input=dict(placed_acceptance=joint_acceptance,
        selected=len(joint_candidates.get('keep',[])),aux_cells=len(joint_candidates.get('aux',{})),
        rejected_candidates=[d for d in joint_candidates.get('decisions',[]) if d.get('status')!='selected'],
        bounded_retry=(ROOT/'generic/rejected_attempt0').exists(),margin_ns=joint_candidates.get('margin_ns')),
    local_replication=dict(checks=local_checks, timing_groups=local_timing, replicas=len(replicas)),
    timing=timing, fanout=fanout, sll_reservation=dict(enabled=sll_enabled, removed_before_route=sll_removed if sll_enabled else None, acceptance=sll_ok, routed_bundles=sll_usage))
dcp=ROOT/'generic/implementation/post_route.dcp'
if dcp.exists(): result.update(dcp=str(dcp),dcp_sha256=digest(dcp),dcp_bytes=dcp.stat().st_size)
(ROOT/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
stage_rows='\n'.join(f"|{r['name']}|{duration(r['seconds'])}|{'编译' if r['included_in_compile_time'] else ('复用，不重复计时' if r.get('reused') else '前置测试')}|" for r in state['stages'])
extraction_rows='\n'.join(f"|{r['stage']}|{r['measured_call_seconds']:.3f}|{sum(x['calls'] for x in r['calls'].values())}|" for r in timing_extraction)
timing_rows='\n'.join(f"|{s}|{v['clock_period_ns']}|{v['wns_ns']}|{v['tns_ns']}|{v['whs_ns']}|{v['ths_ns']}|" for s,v in timing.items())
module_rows='\n'.join(f"|{r['module']}|{r['planned_regions']}|{r['soft']}|" for r in rows('generic/audit_routed/module_constraints.tsv'))
spill_rows='\n'.join(f"|{r['original_module']}|{r['inside_or_outside']}|{r['retained_original_cells']}|" for r in rows('generic/audit_routed/soft_region_spill.tsv'))
application=rows('base/patch_0/application.tsv')
regional=rows('generic/implementation/regional_candidates.tsv')
selected=[r for r in regional if r.get('status')=='selected']
base_luts=sum(int(r['new_luts']) for r in application)
for name in ['regions.png','estimated_utilization.png']:
    src=ROOT/'inputs/figures'/name
    if src.exists(): (fig/name).write_bytes(src.read_bytes())
bars=[]
bar_values = [(f"Current {loc['clock_period_ns']} ns", elapsed)]
if has_reference:
    bar_values.insert(0, (f"Reference {loc.get('reference_clock_ns')} ns", reference_seconds))
for i,(name,seconds) in enumerate(bar_values):
    width=seconds/max(*(v for _,v in bar_values),1)*620
    bars.append(f'<text x="10" y="{35+i*55}" font-size="15">{html.escape(name)}</text><rect x="180" y="{15+i*55}" width="{width:.1f}" height="28" fill="{["#7b8794","#267fad"][i]}"/><text x="810" y="{35+i*55}" font-size="14">{duration(seconds)}</text>')
(fig/'runtime.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="940" height="135"><rect width="940" height="135" fill="white"/>'+''.join(bars)+'</svg>')
solution = 'core_solution.json' if (ROOT/'inputs/core_solution.json').exists() else 'solution.json'
solution_link = f'[原方案](../inputs/{solution})' if (ROOT/'inputs'/solution).exists() else '原方案未单独提供'
images = '\n\n'.join(f'![{name}](figures/{name})' for name in ['regions.png','estimated_utilization.png'] if (fig/name).exists())
comparison_note = (f"历史参考周期 {loc.get('reference_clock_ns')} ns，服务器负载也可能不同，耗时差额不能全部归因于脚本。"
                   if has_reference else '本轮没有同起点、同周期的完整耗时对照；分别记录各阶段耗时，不用历史局部运行的总时间推断完整流程加速比例。')
runtime_note = (f"历史合计 **{duration(reference_seconds)}**；完整运行结束后的差额为 `{result['saved_seconds']}` 秒。"
                if has_reference else '没有可直接比较的完整耗时基准；提速效果需结合阶段计时和等价验证判断。')
input_scope = '从干净 post-opt 重新实现'
policy_note = '全局 WNS 不得低于修改前'
flow_scope = '保留基础浅树、三次正常 placement、一次完整 routing及独立重开'
if loc.get('base_replay'):
    replay=json.loads((ROOT/'replay_base.json').read_text()) if (ROOT/'replay_base.json').exists() else {}
    input_scope = '从既有第二次 placement checkpoint 独立回放'
    comparison_note = '本轮复用已有 seed/base；耗时仅从第二次布局 DCP 的重新打开开始，不与完整流程耗时直接比较。'
    runtime_note = '不计入已复用的前两次布局；不是从 post-opt 开始的完整编译时间。'
    flow_scope = '复用前两次 placement 和基础浅树，本次重新执行联合复制、后续 placement、一次完整 routing及独立重开'
if loc.get('joint_wns_policy') == 'positive':
    policy_note = '本次临时要求全局 WNS > 0，允许相比修改前下降；逐端点、TNS及hold规则保持不变'
sll_note = ''
if sll_enabled:
    sll_note = f'''本轮为 SLL 容量引导对照：以第一组最终 placement 对应的初始 SLL Assignment 逐列需求为依据，对需求/容量≥80%的 bundle 临时占用480/1440条（1/3）；最终placement后、完整routing前移除。占位不连接真实数据路径。移除与连接检查：{sll_removed}；最终48个bundle的实际使用已回读：{len(sll_usage)==48}。

占位明细：[配对通道](../sll_reservation/reservations.tsv)；删除证据：[检查](../sll_reservation/removed.tsv)；最终实测：[逐bundle资源](../generic/reopened/sll_usage/routed_sll_bundles.tsv)。首轮与本轮同周期、同floorplan和fanout配置，临时SLL占位为实验变量。方法参考[论文 VI-C / VII-B](https://jasonlau.io/research-papers/10.1109-ICCAD66269.2025.11240757.pdf)，80%阈值和1/3比例采用用户指定值。'''
report=f'''# {case_name} / {loc['clock_period_ns']} ns 后端实验

状态：**{result['status']}**。各验收项：`{json.dumps(result['gates'],ensure_ascii=False)}`。

## 输入与范围

服务器 eda070，独立目录 `{ROOT}`。输入 `{loc['post_opt']}`，SHA256 `{loc['post_opt_sha256']}`。
采用用户提供的 floorplan、{loc.get('module_count', '未提供')} 个模块、Vivado 2023.2 / 8 线程，周期 {loc['clock_period_ns']} ns；{input_scope}。无 RTL、partition 或流水级修改。
{comparison_note} 输入哈希前后不变：{state['input_unchanged']}。

## 求解结果

复用指定 floorplan，不重新求解。原始输入和资源估计见 [输入清单](../input_manifest.json) 与 {solution_link}。

|模块|原软范围 CR|IS_SOFT|
|---|---|---|
{module_rows or '|尚未完成物理审计|未测量|未测量|'}

{images}

## 目标值和覆盖范围

目标是验证 FF 与 D 输入完整组合逻辑联合复制、输入时序预筛及布局后 STA 门槛，保持同一模块 floorplan，最终 {loc['clock_period_ns']} ns WNS>0。不重新求解 floorplan。
{flow_scope}。布局后门槛：{policy_note}。模型比较仅复制 FF、源端局部 MUX 加目标端末级 MUX、整体目标端复制；复制完整 LUT/MUX 组并检查所有数据和选择输入。D 与 Q 时序分别保护。默认预筛 setup 余量0.2ns，模型是相对原路径的 CR 距离启发式估计，不能代替最终 STA。

候选详情见 [联合规划](../generic/implementation/joint_candidates.json)，布局后门槛见 [验收](../generic/implementation/joint_placed/acceptance.json)。本版独立 LUT 广播副本暂缓，由基础与区域 fanout 流程继续处理；未支持对象明确标注。新副本使用整SLR硬父区域和CR矩形软子区域，不固定LOC/BEL，原模块约束保持不变。布局后输入/控制/输出、共享输入受影响端点、全局WNS/TNS和hold必须通过门槛；拒绝时最多从未修改的第二次布局checkpoint重试一次，失败现场保留。


## Fanout 处理

基础树首轮处理 {len(application)} 根网络，新增 {base_luts} 个 LUT1；区域处理选中 {len(selected)} 根网络。
本轮新增功能副本 {len(replicas)} 个，见 [副本清单](../generic/implementation/replicas.tsv)。输入、控制与输出 setup/hold 明细见 [时序分组](../generic/reopened/local_timing_groups.tsv)，整 SLR、精确连接、原 floorplan 和移动性见 [扩展检查](../generic/reopened/local_structure.tsv)。
同级 FF/LUT 的实际数量和连接核验见 [结构检查](../generic/reopened/structural_pass.txt)，区域覆盖见 [区域检查](../generic/reopened/regional_structure.tsv)。
最终 fanout：`{fanout}`。普通逻辑要求 <100，内部树目标 96；时钟/常量与不支持项见 [全量候选扫描](../generic/reopened/fanout_final/high_fanout.tsv)。
结构四阶段检查：{structure_ok}；移动与软区域契约：{mobility_ok}，详见 [位置检查](../generic/reopened/mobility/PASS)。未通过的 fanout 项标注为验收注释，保留完整结果，不作为程序执行失败。

## 约束验证和物理实现

{sll_note}

|阶段|周期/ns|WNS/ns|TNS/ns|WHS/ns|THS/ns|
|---|---:|---:|---:|---:|---:|
{timing_rows or '|未完成|未测量|未测量|未测量|未测量|未测量|'}

完整布通且 routing error=0：{routed_ok}。详细状态：

```
{route or '尚未生成 routing 报告。'}
```

最终 DCP：`{result.get('dcp','尚未生成')}`。SHA256：`{result.get('dcp_sha256','未测量')}`。
物理审计复用活动会话，保留模块范围、CR 资源、溢出、拥塞及路径族报告。

|模块|区域内外|保留原始 primitive 数|
|---|---|---:|
{spill_rows or '|未完成|未测量|未测量|'}

模块统计不猜测新增/重命名单元归属；软区域溢出单列。实际 CR 资源见 [资源明细](../generic/audit_routed/cr_primitive_counts.tsv)。

## 已完成测试

- 本次 {loc['clock_period_ns']} ns 时钟、审计接入及恢复边界测试：[结果](../tests/local_results.json)。
- 完整层级连接、浅树策略、原生区域修改、端到端布线/重开及本地回归记录均见上述验证结果。
- 小型测试通过不代替本轮 {case_name} 的实际验收。
- 干净输入核验：[结果](../seed/clean_input.tsv)。
- 四阶段结构与最终时序核验按实际状态列出，不将未生成报告视为通过。

## 耗时、风险与后续

|阶段|墙钟时间|口径|
|---|---:|---|
{stage_rows}

编译阶段合计 **{duration(elapsed)}**；{runtime_note} 前置测试与内存排队单列，不计入编译阶段。
新增最终 fanout 扫描耗时 `{fanout.get('scan_elapsed_ms','未测量')}` ms；不会通过删除该检查获得加速。

时序提取模式：`{loc.get('timing_extraction','reference')}`。保留全量受影响端点、逐端点 setup/hold 和原验收规则；以下为被计时调用合计，完整阶段还包括文件生成和报告，不与阶段总时间混用。

|检查阶段|计时调用合计/秒|调用数|
|---|---:|---:|
{extraction_rows}

![编译时间](figures/runtime.svg)

本轮保持fanout<100，内部构树目标96、原生残余复制目标80，沿用上轮同一floorplan。{flow_scope}。耗时不是成功门槛；单次历史比较不能隔离路由搜索或系统负载波动。DONT_TOUCH 保留恒等树逻辑结构，位置自由主要交给 placer；不宣称已完全解除 router 逻辑优化限制。软窗口允许溢出，模块 floorplan 和 FF/CE 约束单独验收。失败/未达标时保留所有输出，原因见 [状态](../status.json)。
'''
(out/'实验报告.md').write_text(report)
print(json.dumps(result,ensure_ascii=False),flush=True)
