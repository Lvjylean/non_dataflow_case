"""Structural locality proposals and exact physical-graph admission.

Virtual terminals never replace the immutable native direct-edge inventory.
"""
import argparse
import collections
import csv
import hashlib
import json
import math
import re
from pathlib import Path
import statistics

import broadcast_components as broadcast
import cone_locality as locality
import joint_input as joint


def read_rows(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def special_source(key):
    return key.startswith(('constant ', 'clock '))


def coordinate(value):
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if math.isfinite(value) else None


def position(cell,name):
    x,y=coordinate(cell.get('x')),coordinate(cell.get('y'))
    if not re.fullmatch(r'SLR\d+',cell.get('slr','')) or x is None or y is None:
        raise ValueError('missing_position:'+name)
    return cell['slr'],x,y


def inventory(folder):
    cells = {}
    for r in read_rows(folder/'cells.tsv'):
        cells[r['name']] = dict(ref=r['ref'], slr=r['slr'],
            x=coordinate(r['x']), y=coordinate(r['y']),
            config={'INIT':r['init']} if r.get('init') else {}, inputs={},
            editable=r['editable'] in {'1','true','True'}, status=r.get('status',''))
    nets = collections.defaultdict(list)
    for r in read_rows(folder/'edges.tsv'):
        driver, sink = r['driver'], r['sink']
        if not special_source(driver):nets[driver].append(sink)
        if '/' not in sink:continue
        cell, pin = sink.rsplit('/',1)
        if cell in cells:
            old = cells[cell]['inputs'].get(pin)
            if old is not None and old != driver:
                raise ValueError('Nonunique native pin: '+sink)
            cells[cell]['inputs'][pin] = driver
    # Duplicate canonical leaf edges indicate an extractor bug, not more loads.
    for key,pins in nets.items():
        if len(pins)!=len(set(pins)):raise ValueError('Duplicate native edge: '+key)
    return cells, {k:sorted(v) for k,v in nets.items()}


def emit(path, variables):
    with Path(path).open('w') as stream:
        for name, value in variables.items():
            stream.write('set '+name+' '+joint.word(joint.tcl(value))+'\n')


def uid(text):
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def center(cells, pins):
    points=[position(cells[p.rsplit('/',1)[0]],p.rsplit('/',1)[0]) for p in pins]
    return statistics.median(p[1] for p in points),statistics.median(p[2] for p in points)


def prepare(folder, min_effective=16, max_candidates=1024, cone_budget=256):
    cells,nets=inventory(folder)
    components=broadcast.discover(cells,nets,min_effective=min_effective)
    cones=locality.discover(cells,nets,max_cells=128)
    requests=[]; decisions=[]
    for key,c in sorted(components['components'].items()):
        for slr,pins in sorted(c['terminals'].items()):
            if slr==c['root_slr'] or not pins:continue
            ident=key+'@'+slr
            name='sbeco_local_ff_'+uid(ident)+'_'+slr
            try:
                for node in [c['root_cell'],*c['transparent'],*(p.rsplit('/',1)[0] for p in pins)]:
                    position(cells[node],node)
                tree=broadcast.plan_component(c,slr,name,cells,nets,branch_limit=96)
                x,y=center(cells,pins)
                requests.append(dict(id=ident,key=key,replica=name,target=slr,x=x,y=y,
                    terminals=pins,tree=tree,effective=len(pins),kind='broadcast'))
            except ValueError as error:
                decisions.append(dict(id=ident,status=str(error)))
    requests.sort(key=lambda r:(-r['effective'],r['id']))
    for r in requests[max_candidates:]:decisions.append(dict(id=r['id'],status='candidate_budget'))
    requests=requests[:max_candidates]
    cc=sorted(cones['candidates'],key=lambda c:(-len(c['target_sinks']),c['id']))
    for c in cc[cone_budget:]:decisions.append(dict(id=c['id'],status='cone_candidate_budget'))
    cc=cc[:cone_budget]
    templates=set(); control_aliases=set(); origin,equiv=aliases(cells)
    for r in requests:
        ff=r['key'].rsplit('/',1)[0]; templates.add(ff)
        templates.update(r['tree']['metadata'].get('reused_nodes',[]))
        for item in r['tree']['clones'].values():
            if item.get('origin'):templates.add(item['origin'])
        for pin,key in cells[ff]['inputs'].items():
            if pin not in {'CE','R','S'} or special_source(key):continue
            for alias in equiv.get(origin(key),[]):
                name=alias.rsplit('/',1)[0]
                if cells[name]['slr']==r['target']:control_aliases.add(name)
    for c in cc:templates.update(c['cone'])
    data=dict(schema='broadcast-locality-v1',requests=requests,cones=cc,
        decisions=decisions,discovery=dict(broadcast=components['decisions'],cone=cones.get('rejected',[])))
    (folder/'proposals.json').write_text(json.dumps(data,indent=2)+'\n')
    fields={r['id']:{k:r[k] for k in ('key','replica','target','x','y','terminals')} for r in requests}
    cone_targets=collections.defaultdict(set)
    for c in cc:cone_targets[c['root']].update(c['target_sinks'])
    emit(folder/'requests.tcl',dict(bl_requests=fields,bl_templates=sorted(templates),
        bl_control_aliases=sorted(control_aliases),
        bl_cone_targets={key:sorted(pins) for key,pins in sorted(cone_targets.items())},
        bl_cone_roots=sorted({c['root'] for c in cc})))
    print(json.dumps(dict(broadcast_candidates=len(requests),cone_candidates=len(cc),templates=len(templates))))


def aliases(cells):
    cache={};active=set()
    def origin(key):
        if key in cache:return cache[key]
        if key in active:raise ValueError('Identity cycle')
        active.add(key);c=cells.get(key.rsplit('/',1)[0],{})
        if c.get('ref')=='LUT1' and c.get('editable') and str(c.get('config',{}).get('INIT','')).lower()=="2'h2":
            src=c.get('inputs',{}).get('I0')
            result=origin(src) if src else key
        else:result=key
        active.remove(key);cache[key]=result;return result
    groups=collections.defaultdict(list)
    for name,c in cells.items():
        if c['ref']=='LUT1' and c['editable']:
            key=name+'/O';groups[origin(key)].append(key)
    return origin,groups


class DirectGraph:
    """Transactional direct-edge admission with one global reverse index."""
    def __init__(self,nets,cells=None):
        self.nets=nets;self.cells=cells;self.olddriver={}
        self.expected={};self.moves={};self.new_inputs={};self.clones={};self.outputs=set()
        self.boundary_checked=set()
        for key,pins in nets.items():
            if special_source(key):continue
            for pin in pins:
                if pin in self.olddriver:raise ValueError('Multiple drivers: '+pin)
                self.olddriver[pin]=key

    @staticmethod
    def output(name,cell):
        return name+'/'+('Q' if cell['ref'] in {'FDRE','FDSE'} else 'O')

    def boundary_source(self,key):
        # ``cells=None`` is only the pure direct-graph utility. Production always
        # supplies the full native inventory and fails closed on missing metadata.
        if self.cells is None or key in self.boundary_checked:return
        if '/' not in key:raise ValueError('unsupported_boundary_source:'+key)
        name,pin=key.rsplit('/',1);cell=self.cells.get(name)
        if cell is None:raise ValueError('missing_boundary_source:'+key)
        ref=cell.get('ref','')
        supported=((ref in {'FDRE','FDSE'} and pin=='Q') or
                   (re.fullmatch(r'(LUT[1-6]|MUXF[789])',ref) and pin=='O') or
                   (re.fullmatch(r'RAMB(18|36)E[12]',ref) and re.fullmatch(r'(DOUTADOUT|DOUTBDOUT|DOUTPADOUTP|DOUTPBDOUTP|DOADO|DOBDO|DOPADOP|DOPBDOP)\[\d+\]',pin)) or
                   (ref in {'URAM288','URAM288_BASE'} and re.fullmatch(r'DOUT_[AB]\[\d+\]',pin)))
        if not supported:raise ValueError('unsupported_boundary_primitive:'+key+':'+ref)
        position(cell,name)
        reasons={r for r in cell.get('status','').split(',') if r}
        # Most non-editable reasons are unsafe for extra source loads as well:
        # protected IP/hierarchy, ASYNC_REG, fixed route, clocks, ambiguity,
        # missing metadata or an unknown future exclusion all remain barriers.
        unsafe=reasons-{'port_boundary'}
        if unsafe:raise ValueError('protected_boundary_source:'+key+':'+','.join(sorted(unsafe)))
        if any(s.startswith('barrier PORT:') for s in self.nets.get(key,[])):
            raise ValueError('external_output_boundary:'+key)
        if reasons=={'port_boundary'}:
            # A pre-existing FF can legitimately read a top-level data input.
            # Only its internal Q acquires a load; no FF input is changed.
            if ref not in {'FDRE','FDSE'} or not cell.get('inputs',{}).get('D','').startswith('barrier PORT:'):
                raise ValueError('unsupported_port_boundary_source:'+key)
        elif not cell.get('editable',False):
            raise ValueError('unclassified_boundary_source:'+key)
        self.boundary_checked.add(key)

    def admit(self,additions,rewires):
        extra={}
        for name,c in additions.items():
            if name in self.clones:
                if self.clones[name]!=c:raise ValueError('conflicting_clone')
            else:
                if self.cells is not None and name in self.cells:raise ValueError('clone_name_collision')
                extra[name]=c
        new_outputs={self.output(n,c) for n,c in extra.items()}
        touched={};moves={};new_inputs={}
        def valid_source(key):
            if not special_source(key) and key not in self.nets and key not in self.outputs and key not in new_outputs:
                raise ValueError('unknown_source:'+key)
            if not special_source(key) and key not in self.outputs and key not in new_outputs:
                self.boundary_source(key)
        def touch(key):
            if key not in touched:touched[key]=set(self.expected.get(key,self.nets.get(key,[])))
            return touched[key]
        for output in new_outputs:touch(output)
        for pin,target in rewires.items():
            if pin not in self.olddriver:raise ValueError('Missing real sink: '+pin)
            if '/' not in pin:raise ValueError('external_sink:'+pin)
            if self.cells is not None:
                obj=self.cells.get(pin.rsplit('/',1)[0],{})
                if not obj.get('editable',False):raise ValueError('protected_sink:'+pin)
                if pin.rsplit('/',1)[1] in {'C','CLK','CLKA','CLKB','CLK_A','CLK_B'}:
                    raise ValueError('clock_sink:'+pin)
            if special_source(target):raise ValueError('rewire_changes_signal_to_constant_or_clock')
            valid_source(target)
            old=self.olddriver[pin]
            if pin in self.moves:
                if self.moves[pin][1]!=target:raise ValueError('overlapping_sink_owner')
                continue
            if old==target:continue
            touch(old).remove(pin);touch(target).add(pin);moves[pin]=[old,target]
        for name,c in extra.items():
            for pin,key in c['inputs'].items():
                full=name+'/'+pin;valid_source(key);new_inputs[full]=key
                if not special_source(key):touch(key).add(full)
        if any(len(v)>=100 for v in touched.values()):raise ValueError('projected_shared_fanout')
        # Commit only after all checks. Rejections leave previous candidates intact.
        self.expected.update(touched);self.moves.update(moves)
        self.new_inputs.update(new_inputs);self.clones.update(extra);self.outputs.update(new_outputs)

    def graph(self):
        return dict(expected={k:sorted(v) for k,v in self.expected.items()},
                    moves=dict(self.moves),new_inputs=dict(self.new_inputs))


def direct_graph(nets,clones,rewires):
    graph=DirectGraph(nets);graph.admit(clones,rewires);return graph.graph()


def slr_bounds(cells):
    bounds={}
    for c in cells.values():
        slr=c.get('slr');x=c.get('x');y=c.get('y')
        if not slr or not isinstance(x,(int,float)) or not isinstance(y,(int,float)):continue
        if not math.isfinite(x) or not math.isfinite(y):continue
        old=bounds.get(slr,(x,x,y,y));bounds[slr]=(min(old[0],x),max(old[1],x),min(old[2],y),max(old[3],y))
    return bounds


class NativeTemplates:
    """Fail closed per candidate, without rejecting unrelated unknown cells."""
    def __init__(self,cells,inv,statuses):
        self.cells=cells;self.inv=inv;self.statuses=statuses
        self.checked=set();self.position_checked=set()

    def check_position(self,name):
        if name in self.position_checked:return
        if name not in self.cells or name not in self.inv.cells:
            raise ValueError('missing_native_cell:'+name)
        native=self.cells[name];record=self.inv.cells[name]
        a=position(native,name);b=position(record,name)
        if native['ref']!=record['ref'] or a[0]!=b[0] or any(abs(x-y)>1e-6 for x,y in zip(a[1:],b[1:])):
            raise ValueError('native_cell_position_or_ref_mismatch:'+name)
        self.position_checked.add(name)

    def check(self,name):
        if name in self.checked:return
        status=self.statuses.get(name,'missing')
        if status!='supported':raise ValueError('unsupported_template:'+name+':'+status)
        self.check_position(name)
        obj=self.cells[name];ref=obj['ref'];native=obj.get('inputs',{})
        edges=self.inv.edges.get(name,{})
        if ref in {'FDRE','FDSE'}:
            required={'D','CE','R' if ref=='FDRE' else 'S'}
            if set(native)-{'C'}!=required:
                raise ValueError('incomplete_native_inputs:'+name)
            expected=required|{'C'}
        elif re.fullmatch(r'LUT[1-6]',ref):expected={'I'+str(i) for i in range(int(ref[3:]))}
        elif re.fullmatch(r'MUXF[789]',ref):expected={'I0','I1','S'}
        else:raise ValueError('unsupported_template_primitive:'+name+':'+ref)
        native_expected=expected-({'C'} if ref in {'FDRE','FDSE'} and 'C' not in native else set())
        if set(native)!=native_expected or set(edges)!=expected:
            raise ValueError('incomplete_template_inputs:'+name)
        for pin,e in edges.items():
            key=e.get('key','');kind=e.get('kind','');source=e.get('source_cell','')
            if pin in native and native[pin]!=key:
                raise ValueError('template_input_mismatch:'+name+'/'+pin)
            if pin=='C' and ref in {'FDRE','FDSE'}:
                if kind!='clock' or not key.startswith('clock ') or source:
                    raise ValueError('unsupported_template_clock:'+name)
            elif kind=='constant':
                if not key.startswith('constant ') or source:
                    raise ValueError('invalid_template_constant:'+name+'/'+pin)
            elif kind=='ordinary':
                if special_source(key) or '/' not in key or source!=key.rsplit('/',1)[0]:
                    raise ValueError('template_source_mismatch:'+name+'/'+pin)
                self.check_position(source)
            else:raise ValueError('unsupported_template_input_kind:'+name+'/'+pin)
        self.checked.add(name)


def cone_timing(record,key):
    if not record or not record.get('max'):raise ValueError('missing_cone_setup_path:'+key)
    if record.get('status')!='supported':raise ValueError('unsupported_cone_timing:'+key+':'+record.get('status','missing'))
    start,end=record.get('start_clock'),record.get('end_clock')
    requirement,period=coordinate(record.get('requirement')),coordinate(record.get('period'))
    slack=coordinate(record.get('max'))
    if not start or start!=end:raise ValueError('unsupported_cone_clock_pair:'+key)
    if requirement is None or period is None or period<=0 or abs(requirement-period)>1e-5:
        raise ValueError('unsupported_cone_timing_exception:'+key)
    if slack is None:raise ValueError('invalid_cone_setup_slack:'+key)
    return slack


def finish(folder, margin=.2, max_added=8192, excluded=()):
    cells,nets=inventory(folder);proposals=json.loads((folder/'proposals.json').read_text())
    inv=joint.Inventory(folder.parent);allrows={r['id']:r for r in inv.candidates}
    baseline={r['key']:r for r in read_rows(folder/'through_slacks.tsv')}
    status_path=folder/'template_status.tsv'
    statuses={r['cell']:r['status'] for r in read_rows(status_path)} if status_path.exists() else {}
    native=NativeTemplates(cells,inv,statuses)
    origin,equiv=aliases(cells)
    clones={};rewires={};kept=[];owners={};decisions=list(proposals['decisions']);estimates={};copies={};hints={};reused_positions={}
    excluded=set(excluded)
    template=next((n for n,c in cells.items() if c['ref']=='LUT1' and c['config'].get('INIT', '').lower()=="2'h2" and c['editable']),None)
    resources=dict(inv.used)
    graph_ledger=DirectGraph(nets,cells);bounds=slr_bounds(cells)

    def admit(ident, additions, changes, owner, estimate):
        nonlocal clones,rewires,resources
        if ident in excluded:raise ValueError('rejected_by_placed_timing_guard')
        if any(p in rewires and rewires[p]!=v for p,v in changes.items()):raise ValueError('overlapping_sink_owner')
        if any(n in clones and clones[n]!=v for n,v in additions.items()):raise ValueError('conflicting_clone')
        extra={n:c for n,c in additions.items() if n not in clones}
        if len(clones)+len(extra)>max_added:raise ValueError('total_resource_budget')
        needed=collections.Counter((c['slr'],'FF' if c['ref'] in {'FDRE','FDSE'} else 'LUT' if c['ref'].startswith('LUT') else c['ref']) for c in extra.values())
        if any(resources.get(k,0)+n>inv.capacity.get(k,0) for k,n in needed.items()):raise ValueError('slr_resource_budget')
        graph_ledger.admit(additions,changes)
        clones.update(additions);rewires.update(changes)
        for k,n in needed.items():resources[k]=resources.get(k,0)+n
        kept.append(ident);owners[ident]=sorted(set(owner));estimates[ident]=estimate
        decisions.append(dict(id=ident,status='selected',**estimate))

    for request in proposals['requests']:
        ident=request['id']
        try:
            if ident in excluded:raise ValueError('rejected_by_placed_timing_guard')
            row=dict(allrows[ident]);tree=request['tree'];ffcell=request['key'].rsplit('/',1)[0]
            native.check(ffcell)
            for name in getattr(inv,'cones',{}).get(request['key'],[]):native.check(name)
            for pin in request['terminals']:native.check_position(pin.rsplit('/',1)[0])
            row['loads']=str(len(tree.get('expected',{}).get(request['replica']+'/Q',[])))
            if not int(row['loads']):
                row['loads']=str(sum(v==request['replica']+'/Q' for v in tree['rewires'].values())+sum(c['inputs']['I0']==request['replica']+'/Q' for c in tree['clones'].values()))
            row['detached_loads']=str(sum(p in nets.get(request['key'],[]) for p in tree['rewires']))
            control_choices={}
            for pin,e in inv.edges[ffcell].items():
                if pin not in {'CE','R','S'} or e['kind']!='ordinary':continue
                possible=[]
                for key in sorted(set([e['key'],*equiv.get(origin(e['key']),[])])):
                    name=key.rsplit('/',1)[0]
                    try:
                        if key==e['key']:native.check_position(name)
                        else:native.check(name)
                        possible.append(key)
                    except ValueError as error:
                        decisions.append(dict(id=ident+':control_alias:'+key,status=str(error)))
                if not possible:raise ValueError('missing_control_inventory:'+pin)
                control_choices[pin]=sorted(set(possible))
            # Evaluate a bounded set of CR centers using BOTH input and output delay proxies.
            xmin,xmax,ymin,ymax=bounds[row['target']]
            old=joint.pos(inv.cells[ffcell]);cx=min(max(old[1],xmin),xmax);cy=min(max(old[2],ymin),ymax)
            choices={(float(row['x']),float(row['y'])),(cx,cy),((cx+float(row['x']))/2,(cy+float(row['y']))/2)}
            alternatives=[]
            for x,y in sorted(choices):
                new=(row['target'],x,y)
                controls={pin:min(keys,key=lambda k:(joint.wire(joint.pos(inv.cells[k.rsplit('/',1)[0]]),new),k)) for pin,keys in control_choices.items()}
                rr=dict(row,x=str(x),y=str(y),control_drivers=controls);inv.candidates=[rr]
                plan=joint.build(inv,margin=margin,max_added=max_added,excluded=excluded)
                if ident not in plan['keep']:continue
                gain=min(joint.wire(old,(cells[p.rsplit('/',1)[0]]['slr'],cells[p.rsplit('/',1)[0]]['x'],cells[p.rsplit('/',1)[0]]['y']))-joint.wire(new,(cells[p.rsplit('/',1)[0]]['slr'],cells[p.rsplit('/',1)[0]]['x'],cells[p.rsplit('/',1)[0]]['y'])) for p in request['terminals'])
                if gain<=0:continue
                control_slack=min([float(inv.slacks[ffcell+'/'+pin]['max'])-(joint.wire(joint.pos(inv.cells[key.rsplit('/',1)[0]]),new)-joint.wire(joint.pos(inv.cells[inv.edges[ffcell][pin]['source_cell']]),old)) for pin,key in controls.items()] or [float('inf')])
                score=min(plan['estimates'][ident]['predicted_D_slack'],control_slack,gain)
                alternatives.append((score,x,y,plan,controls))
            if not alternatives:raise ValueError('no_joint_input_output_position')
            _,x,y,plan,controls=max(alternatives,key=lambda x:x[:3])
            additions={}
            for name,c in tree['clones'].items():
                origin_cell=c.get('origin') or template
                if not origin_cell:raise ValueError('missing_identity_template')
                native.check(origin_cell)
                additions[name]=dict(c,origin=origin_cell,key=origin_cell+'/O')
            inputs={pin:e['key'] for pin,e in inv.edges[ffcell].items()}
            inputs.update({p.rsplit('/',1)[1]:key for p,key in plan['links'].items() if p.startswith(request['replica']+'/')})
            additions[request['replica']]=dict(ref=cells[ffcell]['ref'],origin=ffcell,key=request['key'],slr=row['target'],x=x,y=y,inputs=inputs)
            for name,item in plan['aux'].items():
                original=item['key'].rsplit('/',1)[0]
                native.check(original)
                additions[name]=dict(item,origin=original,ref=inv.cells[original]['ref'],inputs={p.rsplit('/',1)[1]:k for p,k in plan['links'].items() if p.startswith(name+'/')})
            retained=tree['metadata'].get('reused_nodes',[])
            for name in retained:native.check(name)
            if any(cells[n]['slr']!=row['target'] for n in retained):raise ValueError('nonlocal_reused_subtree')
            if any(n in reused_positions and reused_positions[n]!=row['target'] for n in retained):raise ValueError('conflicting_reused_subtree')
            owner=set(plan['owners'][ident])|set(c['origin'] for c in additions.values())|set(p.rsplit('/',1)[0] for p in tree['rewires'])|set(retained)
            estimate=dict(plan['estimates'][ident],kind='broadcast',effective_loads=request['effective'],direct_loads=len(nets[request['key']]),position=[x,y],control_drivers=controls)
            admit(ident,additions,tree['rewires'],owner,estimate)
            for n in retained:reused_positions[n]=row['target']
            copies.setdefault(request['key'],{})[row['target']]=request['replica']
        except (ValueError,KeyError) as error:decisions.append(dict(id=ident,status=str(error)))

    for candidate in proposals['cones']:
        ident=candidate['id']
        try:
            if ident in excluded:raise ValueError('rejected_by_placed_timing_guard')
            slack=cone_timing(baseline.get(candidate['root']),candidate['root'])
            for name in candidate['cone']:native.check(name)
            for pin in candidate['target_sinks']:native.check_position(pin.rsplit('/',1)[0])
            p=locality.plan_candidate(cells,nets,candidate,max_cells=128)
            additions={c['name']:dict(c,origin=original) for original,c in p['clones'].items()}
            assignment={original:(c['slr'],c['x'],c['y']) for original,c in p['clones'].items()}
            root=candidate['root'].rsplit('/',1)[0];cone=set(candidate['cone'])
            delta=max(joint.delta_bound(inv,root,cone,assignment,
                joint.pos(inv.cells[pin.rsplit('/',1)[0]]),joint.pos(inv.cells[pin.rsplit('/',1)[0]])) for pin in candidate['target_sinks'])
            predicted=slack-delta
            if delta>=0 or predicted<margin:raise ValueError('cone_input_or_output_margin')
            admit(ident,additions,p['rewires'],p['owners'],dict(kind='cone',predicted_slack=predicted,delta_ns=delta))
        except (ValueError,KeyError) as error:decisions.append(dict(id=ident,status=str(error)))
    graph=graph_ledger.graph()
    graph['replicas']={n:{'key':c['key'],'slr':c['slr']} for n,c in clones.items()};graph['owners']={}
    hints={n:{k:c[k] for k in ('slr','x','y')} for n,c in clones.items()}
    result=dict(schema='joint-input-locality-v1',keep=kept,aux={n:c for n,c in clones.items() if c['ref'] not in {'FDRE','FDSE'}},links=graph['new_inputs'],hints=hints,owners=owners,estimates=estimates,decisions=decisions,reused_positions=reused_positions)
    (folder.parent/'joint_candidates.json').write_text(json.dumps(result,indent=2)+'\n')
    roots=sorted({c['origin'] for c in clones.values()}|set(reused_positions))
    keys=sorted(set(graph['expected'])-set(n+'/'+('Q' if c['ref'] in {'FDRE','FDSE'} else 'O') for n,c in clones.items()))
    emit(folder/'final_plan.tcl',dict(bl_graph=graph,bl_copies=copies,bl_hints=hints,bl_roots=roots,bl_keys=keys,bl_keep=kept,bl_aux=result['aux'],bl_reused=reused_positions))
    print(json.dumps(dict(accepted=len(kept),clones=len(clones),broadcast=len(copies),cone=sum(e['kind']=='cone' for e in estimates.values()))))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','finish']);ap.add_argument('folder',type=Path)
    ap.add_argument('--margin',type=float,default=.2);ap.add_argument('--max-added',type=int,default=8192);ap.add_argument('--exclude',type=Path)
    args=ap.parse_args()
    if args.mode=='prepare':prepare(args.folder)
    else:finish(args.folder,args.margin,args.max_added,json.loads(args.exclude.read_text()) if args.exclude else ())
