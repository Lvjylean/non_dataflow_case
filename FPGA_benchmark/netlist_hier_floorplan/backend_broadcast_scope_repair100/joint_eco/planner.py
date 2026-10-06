"""Pure graph planning; no Vivado/database mutations occur in this module."""
import argparse, collections, copy, csv, json, re
from pathlib import Path

COMB=re.compile(r'^(LUT[1-6]|MUXF[78])$')
def read_tsv(path):
    with Path(path).open() as f:return list(csv.DictReader(f,delimiter='\t'))
def cell(pin):return pin.rsplit('/',1)[0]
def atom(x):
    s=str(x)
    for a,b in [('\\','\\\\'),('"','\\"'),('$','\\$'),('[','\\['),(']','\\]'),('\n','\\n'),('\r','\\r')]:s=s.replace(a,b)
    return '"'+s+'"'
def tcl(x):
    if isinstance(x,dict):return '{'+' '.join(atom(k)+' '+tcl(v) for k,v in x.items())+'}'
    if isinstance(x,(list,tuple)):return '{'+' '.join(tcl(v) for v in x)+'}'
    return atom(x)
class BudgetError(ValueError):
    def __init__(self,driver,targets):
        super().__init__('overbudget_non_LUT:'+driver)
        self.driver=driver;self.targets=targets

def affected_targets(inv,spec,startpins):
    projected={k:set(v) for k,v in inv.loads.items()}
    for pin,(old,new) in spec['changes'].items():projected.setdefault(old,set()).discard(pin);projected.setdefault(new,set()).add(pin)
    for pin,x in spec['connections'].items():
        if x['kind']=='driver':projected.setdefault(x['source'],set()).add(pin)
    pending=list(startpins);seen=set();targets=set()
    while pending:
        p=pending.pop()
        if p in seen:continue
        seen.add(p)
        if p in spec['targets']:targets.add(p);continue
        c=cell(p)
        ref=spec['clones'][c]['config']['ref'] if c in spec['clones'] else inv.cells.get(c,{}).get('ref','')
        if COMB.match(ref):pending.extend(projected.get(c+'/O',[]))
    return targets

class Inventory:
    def __init__(self,folder):
        self.cells={r['name']:r for r in read_tsv(folder/'cells.tsv')}
        self.inputs=collections.defaultdict(dict)
        for r in read_tsv(folder/'edges.tsv'):self.inputs[cell(r['sink'])][r['sink'].rsplit('/',1)[1]]=(r['kind'],r['source'])
        self.loads={r['driver']:r['sinks'].split('|') if r['sinks'] else [] for r in read_tsv(folder/'loads.tsv')}
        self.targets=read_tsv(folder/'targets.tsv')
        self.critical={r['endpoint']:r['cells'].split('|') for r in read_tsv(folder/'critical_paths.tsv')} if (folder/'critical_paths.tsv').exists() else {}
        self.limits={r['driver']:int(r['limit']) for r in read_tsv(folder/'budget_limits.tsv')} if (folder/'budget_limits.tsv').exists() else {}
    def groups(self,cone):
        parent={c:c for c in cone}
        def root(c):
            while parent[c]!=c:parent[c]=parent[parent[c]];c=parent[c]
            return c
        def union(a,b):parent[root(b)]=root(a)
        for c in cone:
            if self.cells[c]['ref'].startswith('MUXF'):
                for p in ['I0','I1']:
                    kind,d=self.inputs[c][p];dc=cell(d)
                    if kind!='driver' or dc not in cone or not COMB.match(self.cells[dc]['ref']):raise ValueError('incomplete_mux_macro:'+c)
                    union(c,dc)
        groups=collections.defaultdict(set)
        for c in cone:groups[root(c)].add(c)
        return dict(groups),{c:root(c) for c in cone}
    def memory_origins(self,c,memo,active):
        if c in memo:return memo[c]
        if c in active:raise ValueError('combinational_cycle:'+c)
        ref=self.cells[c]['ref']
        if 'RAM' in ref:memo[c]={self.cells[c]['slr']};return memo[c]
        if not COMB.match(ref):memo[c]=set();return set()
        active.add(c);v=set()
        for kind,src in self.inputs[c].values():
            if kind=='driver':v.update(self.memory_origins(cell(src),memo,active))
        active.remove(c);memo[c]=v;return v
    def worst_crossings(self,root,assignment):
        memo={}
        def walk(c):
            if c in memo:return memo[c]
            dst=assignment.get(c,self.cells[c]['slr']);cost=0
            for kind,src in self.inputs.get(c,{}).values():
                if kind!='driver':continue
                sc=cell(src);s=assignment.get(sc,self.cells[sc]['slr'])
                cost=max(cost,walk(sc)+int(bool(s and dst and s!=dst)))
            memo[c]=cost;return cost
        return walk(root)

def build(inv,mode='memory_aware',max_added=8192):
    spec={'schema':'getrf-joint-cone-v1','period':6.7,'fanout_lt':100,'clones':{},'changes':{},'connections':{},'targets':{},'reuse':{},'decisions':[]}
    cache={};memory={};counter=0
    def name(c,slr,local):
        nonlocal counter
        key=(c,slr)
        if key in cache:return cache[key]
        if key in local:return local[key]
        counter+=1;local[key]=f'jcone_{counter:05d}_{inv.cells[c]["ref"]}'
        return local[key]
    for target in sorted(inv.targets,key=lambda r:float(r['slack'])):
        ep=target['endpoint'];orig=target['original'];slr=target['slr'];root=cell(target['driver'])
        decision={'endpoint':ep,'original':orig,'before_slack':float(target['slack'])}
        supported= ('ap_CS_fsm_reg' in orig or re.search(r'(tmp_3_reg_17834|tmp_4_reg_18350|tmp_5_reg_13495)_reg',orig))
        if target['status']!='supported' or not supported:
            decision['status']='deferred_unsupported_family_or_cone';spec['decisions'].append(decision);continue
        cone=set(target['cone_cells'].split('|')) if target['cone_cells'] else set()
        try:
            if root not in cone:raise ValueError('root_is_not_supported_combination')
            groups,owner=inv.groups(cone);assign={};group_slr={}
            for g,cs in groups.items():
                origins=set()
                for c in cs:origins.update(inv.memory_origins(c,memory,set()))
                dest=next(iter(origins)) if mode=='memory_aware' and len(origins)==1 else slr
                if root in cs:dest=slr
                if dest not in {'SLR0','SLR1','SLR2','SLR3'}:raise ValueError('unknown_slr')
                group_slr[g]=dest
                for c in cs:assign[c]=dest
            # Clone moved groups and the downstream groups needed to isolate edits.
            affected={g for g,cs in groups.items() if any(inv.cells[c]['slr']!=group_slr[g] for c in cs)}
            if not affected:raise ValueError('no_slr_backtracking_candidate')
            while True:
                more={owner[c] for c in cone for kind,d in inv.inputs[c].values() if kind=='driver' and cell(d) in cone and owner[cell(d)] in affected}
                new=affected|more
                if new==affected:break
                affected=new
            edited=set().union(*(groups[g] for g in affected))
            reuse=set()
            for g in affected:
                cs=groups[g]
                # Existing owned terminal macros may be rewired without orphaning them.
                if all(c.startswith('tgin_') and inv.cells[c]['slr']==group_slr[g] for c in cs) and all(cell(p) in cone or p==ep for c in cs for p in inv.loads.get(c+'/O',[])):
                    reuse.update(cs)
            local={};mapping={c:(c if c in reuse else name(c,assign[c],local)) for c in edited}
            if len(spec['clones'])+len(local)>max_added-256:raise ValueError('global_added_cell_budget')
            if len(local)>512:raise ValueError('endpoint_added_cell_budget')
            changes={};links={}
            for c in edited:
                nc=mapping[c]
                for pin,(kind,src) in inv.inputs[c].items():
                    new=src
                    if kind=='driver' and cell(src) in mapping:new=mapping[cell(src)]+'/'+src.rsplit('/',1)[1]
                    np=nc+'/'+pin
                    if nc==c:
                        if new!=src:changes[np]=[src,new]
                    else:links[np]={'kind':kind,'source':new,'anchor':c+'/'+pin}
            newroot=mapping.get(root,root)+'/O'
            if newroot!=target['driver']:changes[ep]=[target['driver'],newroot]
            for pin,pair in changes.items():
                if pin in spec['changes'] and spec['changes'][pin]!=pair:raise ValueError('conflicting_shared_rewire:'+pin)
            for pin,link in links.items():
                if pin in spec['connections'] and spec['connections'][pin]!=link:raise ValueError('conflicting_shared_clone_input:'+pin)
            if not changes:raise ValueError('no_rewire')
            before=inv.worst_crossings(root,{})+int(inv.cells[root]['slr']!=slr)
            effective={c:assign[c] for c in edited}
            after=inv.worst_crossings(root,effective)+int(effective.get(root,inv.cells[root]['slr'])!=slr)
            critical=getattr(inv,'critical',{}).get(ep,[])
            cb=ca=None
            if critical:
                cb=sum(inv.cells[a]['slr']!=inv.cells[b]['slr'] for a,b in zip(critical,critical[1:]))
                ca=sum(effective.get(a,inv.cells[a]['slr'])!=effective.get(b,inv.cells[b]['slr']) for a,b in zip(critical,critical[1:]))
                if ca>cb:raise ValueError('actual_critical_crossing_regression')
            if after>before and not (critical and ca<cb):raise ValueError('structural_crossing_regression')
            for (c,dest),nc in local.items():
                spec['clones'][nc]={'original':c,'target':dest,'config':{'ref':inv.cells[c]['ref'],'init':inv.cells[c]['init']}}
            spec['connections'].update(links);spec['changes'].update(changes);cache.update(local)
            spec['reuse'].update({c:assign[c] for c in reuse})
            spec['targets'][ep]={'original':orig,'target':slr,'baseline_slack':target['slack']}
            decision.update(status='selected',added=len(local),reused=len(reuse),crossings_before=before,crossings_after=after,cone_cells=len(cone),critical_crossings_before=cb,critical_crossings_after=ca)
        except ValueError as e:decision['status']=str(e)
        spec['decisions'].append(decision)
    if not spec['changes']:raise ValueError('No safe structural candidate')
    # Resolve projected loads jointly. Clone existing LUTs in parallel when needed.
    # No identity stage or new sequential element is introduced.
    expected={k:set(v) for k,v in inv.loads.items()};newpins=collections.defaultdict(list)
    for pin,item in spec['connections'].items():
        if item['kind']=='driver':newpins[item['source']].append(pin)
    for pin,(old,new) in spec['changes'].items():
        expected.setdefault(old,set()).discard(pin);newpins[new].append(pin)
    queue=list(newpins);done=set();helper_count=0
    while queue:
        src=queue.pop(0)
        if src in done:continue
        done.add(src);requests=newpins[src];existing=len(expected.get(src,set()))
        if existing+len(requests)<=getattr(inv,'limits',{}).get(src,96 if cell(src).startswith('rfd_lut_') else 99):continue
        c=cell(src)
        if c not in inv.cells or not re.match(r'^LUT[1-6]$',inv.cells[c]['ref']):raise BudgetError(src,affected_targets(inv,spec,requests))
        groups=collections.defaultdict(list)
        for pin in requests:
            pc=cell(pin)
            dest=spec['clones'][pc]['target'] if pc in spec['clones'] else inv.cells[pc]['slr']
            groups[dest].append(pin)
        newpins[src]=[]
        for slr,pins in groups.items():
            for start in range(0,len(pins),96):
                helper_count+=1;nc=f'jcone_helper_{helper_count:04d}_{inv.cells[c]["ref"]}'
                spec['clones'][nc]={'original':c,'target':slr,'config':{'ref':inv.cells[c]['ref'],'init':inv.cells[c]['init']}}
                for pin in pins[start:start+96]:
                    if pin in spec['changes']:spec['changes'][pin][1]=nc+'/O'
                    else:spec['connections'][pin]['source']=nc+'/O'
                for p,(kind,d) in inv.inputs[c].items():
                    pin=nc+'/'+p;spec['connections'][pin]={'kind':kind,'source':d,'anchor':c+'/'+p}
                    if kind=='driver':
                        newpins[d].append(pin)
                        done.discard(d);queue.append(d)
                if helper_count>256:raise ValueError('helper_budget')
    if len(spec['clones'])>max_added:raise ValueError('helper_exceeded_cell_budget')
    # Functional construction certificate: each clone retains the exact primitive
    # and maps inputs only to functionally equivalent copies of the same driver.
    projected={k:set(v) for k,v in inv.loads.items()}
    for pin,(old,new) in spec['changes'].items():projected.setdefault(old,set()).discard(pin);projected.setdefault(new,set()).add(pin)
    for pin,x in spec['connections'].items():
        if x['kind']=='driver':projected.setdefault(x['source'],set()).add(pin)
    touched={x['source'] for x in spec['connections'].values() if x['kind']=='driver'}|{s for pair in spec['changes'].values() for s in pair}
    for s in touched:
        if len(projected[s])>=100:raise ValueError('final_projected_fanout:'+s)
    spec['projected']={s:len(projected[s]) for s in sorted(touched)}
    return spec

def main():
    p=argparse.ArgumentParser();p.add_argument('inventory',type=Path);p.add_argument('output',type=Path);p.add_argument('--mode',default='memory_aware',choices=['memory_aware','endpoint_local']);a=p.parse_args()
    inv=Inventory(a.inventory);a.output.mkdir(exist_ok=False);rejected=[]
    for iteration in range(len(inv.targets)+1):
        try:spec=build(inv,a.mode);break
        except BudgetError as e:
            candidates=[r for r in inv.targets if r['endpoint'] in e.targets]
            if not candidates:raise
            victim=max(candidates,key=lambda r:float(r['slack']))
            rejected.append(dict(endpoint=victim['endpoint'],original=victim['original'],status='deferred_upstream_FF_budget',driver=e.driver,before_slack=float(victim['slack'])))
            inv.targets=[r for r in inv.targets if r['endpoint']!=victim['endpoint']]
            (a.output/'planning_rejections.json').write_text(json.dumps(rejected,indent=2)+'\n')
    else:raise ValueError('No safe upstream-budget batch')
    spec['decisions'].extend(rejected)
    (a.output/'spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    (a.output/'spec.tcl').write_text('set jc_spec '+tcl(spec)+'\n')
    summary=dict(targets=len(spec['targets']),clones=len(spec['clones']),rewired_pins=len(spec['changes']),reused_cells=len(spec['reuse']),decisions=collections.Counter(x['status'] for x in spec['decisions']),maximum_projected_fanout=max(spec['projected'].values()))
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
if __name__=='__main__':main()
