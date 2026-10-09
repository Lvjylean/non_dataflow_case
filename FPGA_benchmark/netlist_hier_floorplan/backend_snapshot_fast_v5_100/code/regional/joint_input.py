"""Bounded joint FF/input-cone planning; predictions never replace placed STA."""
import argparse
import collections
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re

COMB = re.compile(r'^(LUT[1-6]|MUXF[789])$')


def rows(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def word(value):
    text = str(value)
    for a, b in [('\\', '\\\\'), ('"', '\\"'), ('$', '\\$'), ('[', '\\['), (']', '\\]'),
                 ('\n', '\\n'), ('\r', '\\r')]:
        text = text.replace(a, b)
    return '"' + text + '"'


def tcl(value):
    if isinstance(value, dict):
        value = [item for pair in value.items() for item in pair]
    if isinstance(value, (list, tuple)):
        return ' '.join(word(tcl(x) if isinstance(x, (list, tuple, dict)) else x) for x in value)
    return str(value)


class Inventory:
    def __init__(self, folder):
        folder = Path(folder)
        self.cells = {r['name']: r for r in rows(folder/'ji_cells.tsv')}
        self.edges = collections.defaultdict(dict)
        for r in rows(folder/'ji_edges.tsv'):
            self.edges[r['cell']][r['pin']] = r
        self.cones = collections.defaultdict(set)
        for r in rows(folder/'ji_cones.tsv'):
            self.cones[r['key']].add(r['cell'])
        self.candidates = rows(folder/'ji_candidates.tsv')
        self.loads = {r['key']: int(r['fanout']) for r in rows(folder/'ji_nets.tsv')}
        self.slacks = {r['pin']: r for r in rows(folder/'ji_slacks.tsv')}
        self.capacity = {(r['slr'],r['kind']):int(r['capacity']) for r in rows(folder/'ji_capacity.tsv')}
        self.used = {}
        names=[]
        labels={'CLB LUTs':'LUT','CLB Registers':'FF','F7 Muxes':'MUXF7','F8 Muxes':'MUXF8','F9 Muxes':'MUXF9'}
        for line in (folder/'ji_utilization_slr.rpt').read_text().splitlines():
            cols=[x.strip() for x in line.split('|')[1:-1]]
            if cols and cols[0]=='Site Type':names=[c for c in cols[1:] if re.fullmatch(r'SLR\d+',c)]
            if names and cols and cols[0] in labels:
                for slr,value in zip(names,cols[1:]):self.used[slr,labels[cols[0]]]=int(value)
        if not self.capacity or set(self.capacity)-set(self.used):
            raise ValueError('Incomplete native SLR resource inventory')


def pos(cell):
    return cell['slr'], float(cell['x']), float(cell['y'])


def wire(a, b):
    # Conservative CR-scale proxy, calibrated by the original endpoint slack.
    # Units are ns. Actual placement/routing is always checked independently.
    if not a[0] or not b[0]:
        raise ValueError('unknown_boundary_position')
    crossings = abs(int(a[0][3:])-int(b[0][3:]))
    return .05 + .12*abs(a[1]-b[1]) + .08*abs(a[2]-b[2]) + 1.0*crossings


def groups(inv, cone):
    parents = {c:c for c in cone}
    def root(c):
        while parents[c] != c:
            c = parents[c]
        return c
    for c in cone:
        if inv.cells[c]['ref'].startswith('MUXF'):
            for pin in ['I0', 'I1']:
                e = inv.edges[c][pin]
                src = e['source_cell']
                if e['kind'] != 'ordinary' or src not in cone:
                    raise ValueError('incomplete_mux_macro')
                parents[root(src)] = root(c)
    result = collections.defaultdict(set)
    for c in cone:
        result[root(c)].add(c)
    return list(result.values())


def origins(inv, c, cone, memo=None, active=None):
    memo = {} if memo is None else memo
    active = set() if active is None else active
    if c in memo:
        return memo[c]
    if c in active:
        raise ValueError('combinational_cycle')
    if c not in cone:
        return {inv.cells[c]['slr']} if c in inv.cells else {''}
    active.add(c)
    ans = set()
    for e in inv.edges[c].values():
        if e['kind'] == 'ordinary':
            ans |= origins(inv, e['source_cell'], cone, memo, active)
    active.remove(c)
    memo[c] = ans
    return ans


class StructuralAnalysis:
    """Reuse MUX grouping and origin summaries, never placement or STA verdicts.

    The bounded signature includes every condition read by groups/origins:
    ordered cone members, primitive references, input branch kind/source/key,
    and both cone and boundary SLRs. Geometry, timing, candidate target, controls,
    budgets and shared-load admission are intentionally evaluated afresh.
    """
    def __init__(self, inv):
        self.inv = inv
        self.cache = {}
        self.hits = 0
        self.misses = 0

    def structure(self, inv, cone):
        if inv is not self.inv:
            raise ValueError('structural_analysis_inventory_mismatch')
        # Preserve iteration order because the legacy position averages follow
        # the original macro member order, including floating-point summation.
        members = tuple(cone)
        records = []
        for name in members:
            cell = inv.cells.get(name, {})
            edges = inv.edges.get(name, {})
            branches = tuple((pin, e.get('kind'), e.get('source_cell'), e.get('key'),
                              inv.cells.get(e.get('source_cell'), {}).get('slr'))
                             for pin, e in edges.items())
            records.append((name, cell.get('ref'), cell.get('slr'), branches))
        signature = (members, tuple(records))
        if signature in self.cache:
            self.hits += 1
            return self.cache[signature]
        # Failed/partial grouping is never published as a valid cache entry.
        value = (groups(inv, cone), {})
        self.cache[signature] = value
        self.misses += 1
        return value


def delta_bounds(inv, root, cone, assignment, endpoint_pairs):
    """Evaluate one complete input cone for multiple output endpoints.

    Every data/select branch retains the original maximum-delta calculation.
    Only the root-to-endpoint wire term differs between endpoint pairs; do not
    rebuild its identical recursive cone summary for every receiving pin.
    """
    memo = {}
    active = set()
    def visit(c):
        if c not in cone:
            return 0.0
        if c in memo:
            return memo[c]
        if c in active:
            raise ValueError('combinational_cycle')
        active.add(c)
        b = pos(inv.cells[c]); a = assignment.get(c, b)
        values = []
        for e in inv.edges[c].values():
            if e['kind'] == 'ordinary':
                src = e['source_cell']; old = pos(inv.cells[src]); new = assignment.get(src, old)
                values.append(visit(src) + wire(new, a)-wire(old, b))
        active.remove(c)
        memo[c] = max(values, default=0.0)
        return memo[c]
    before = pos(inv.cells[root]); after = assignment.get(root, before)
    internal = visit(root)
    # Keep the legacy left-to-right floating-point addition/subtraction order.
    return [internal + wire(after, endpoint_after)-wire(before, endpoint_before)
            for endpoint_before, endpoint_after in endpoint_pairs]


def delta_bound(inv, root, cone, assignment, endpoint_before, endpoint_after):
    """Maximum modeled incremental delay across ALL data/select branches."""
    return delta_bounds(inv, root, cone, assignment, [(endpoint_before, endpoint_after)])[0]


def verify_expected_plan(plan, expected_path, evidence_path):
    """Bind a temporary policy experiment to the original structural proposal."""
    expected=json.loads(Path(expected_path).read_text())
    fields=('keep','aux','links','hints')
    differences=[name for name in fields if plan.get(name)!=expected.get(name)]
    evidence=dict(status='PASS' if not differences else 'FAIL',fields=list(fields),
                  differences=differences,selected=len(plan['keep']),aux_cells=len(plan['aux']))
    Path(evidence_path).write_text(json.dumps(evidence,indent=2)+'\n')
    if differences:
        raise ValueError('Replay candidates differ before netlist edits: '+','.join(differences))


def build(inv, margin=.2, max_added=8192, per_endpoint=512, excluded=(), structural_analysis=None):
    result = dict(schema='joint-input-v1', margin_ns=margin, keep=[], aux={}, links={},hints={},
                  decisions=[], estimates={}, owners={}, model='CR-distance-delta-v1')
    excluded = set(excluded)
    projected = dict(inv.loads)
    resources=dict(getattr(inv,'used',{}))
    cache = {}
    for row in sorted(inv.candidates, key=lambda r:(r['key'], r['target'])):
        ident = row['id']; decision = dict(id=ident, key=row['key'], replica=row['replica'])
        try:
            if ident in excluded:
                raise ValueError('rejected_by_placed_timing_guard')
            if row['status'] != 'supported':
                raise ValueError(row['status'])
            if row['ref'] not in {'FDRE','FDSE'}:
                raise ValueError('standalone_LUT_requires_separate_input_timing_model')
            cell = row['key'].rsplit('/',1)[0]; root = row['driver_cell']
            cone = inv.cones[row['key']]
            if structural_analysis is None:
                macro = groups(inv, cone)
                origin_memo = {}
            else:
                macro, origin_memo = structural_analysis.structure(inv, cone)
            target = (row['target'], float(row['x']), float(row['y']))
            before_ff = pos(inv.cells[cell])
            dslack = inv.slacks.get(cell+'/D',{}).get('max','')
            if not dslack:
                raise ValueError('missing_D_setup_path')
            period=inv.cells[cell].get('period','')
            requirement=inv.slacks[cell+'/D'].get('requirement','')
            if not period or not requirement or abs(float(period)-float(requirement))>1e-5:
                raise ValueError('unsupported_clock_or_timing_exception')
            # Controls are protected individually, not offset against Q improvement.
            for pin, e in inv.edges[cell].items():
                if pin not in {'CE','R','S'} or e['kind'] != 'ordinary':
                    continue
                slack = inv.slacks.get(cell+'/'+pin,{}).get('max','')
                if not slack:
                    raise ValueError('missing_control_setup_path:'+pin)
                req=inv.slacks[cell+'/'+pin].get('requirement','')
                if not req or abs(float(period)-float(req))>1e-5:
                    raise ValueError('unsupported_control_timing_exception:'+pin)
                source_key = row.get('control_drivers',{}).get(pin,e['key'])
                src = pos(inv.cells[source_key.rsplit('/',1)[0]])
                old_src = pos(inv.cells[e['source_cell']])
                if float(slack)-(wire(src,target)-wire(old_src,before_ff)) < margin:
                    raise ValueError('control_input_margin:'+pin)
            alternatives = []
            for mode in ['ff_only','memory_local','target_local']:
                if mode != 'ff_only' and not cone:
                    continue
                assignment = {}
                if mode != 'ff_only':
                    for members in macro:
                        source_slrs = set().union(*(origins(inv,c,cone,origin_memo) for c in members))
                        destination = target
                        if mode == 'memory_local' and len(source_slrs)==1 and root not in members:
                            slr = next(iter(source_slrs))
                            matching = [pos(inv.cells[c]) for c in members if inv.cells[c]['slr']==slr]
                            if not matching:
                                matching = [pos(inv.cells[e['source_cell']]) for c in members for e in inv.edges[c].values()
                                            if e['kind']=='ordinary' and inv.cells[e['source_cell']]['slr']==slr]
                            if matching:
                                destination=(slr,sum(p[1] for p in matching)/len(matching),sum(p[2] for p in matching)/len(matching))
                        for c in members:
                            assignment[c] = destination
                delta = delta_bound(inv,root,cone,assignment,before_ff,target)
                predicted = float(dslack)-delta
                if predicted < margin:
                    continue
                # Duplicate complete macros and all necessary downstream logic.
                edited = set()
                if mode != 'ff_only':
                    for members in macro:
                        if root in members or any(assignment[c][0] != inv.cells[c]['slr'] for c in members):
                            edited |= members
                    while True:
                        enlarged = set(edited)
                        for members in macro:
                            if any(e['source_cell'] in edited for c in members for e in inv.edges[c].values()):
                                enlarged |= members
                        if enlarged == edited:
                            break
                        edited = enlarged
                if len(edited)>per_endpoint:
                    continue
                alternatives.append((-predicted,len(edited),mode,assignment,edited,predicted))
            if not alternatives:
                raise ValueError('no_candidate_with_input_margin')
            admitted = None
            for _,_,mode,assignment,edited,predicted in sorted(alternatives):
                aux = {}; mapping = {}; links = {}; newcache = {}
                active = set()
                def clone(c):
                    if c not in edited:
                        return c+'/O'
                    if c in mapping:
                        return mapping[c]+'/O'
                    if c in active:
                        raise ValueError('combinational_cycle')
                    active.add(c); inputs = {}
                    for pin,e in inv.edges[c].items():
                        source=e['key']
                        if e['kind']=='ordinary' and e['source_cell'] in edited:
                            source=clone(e['source_cell'])
                        inputs[pin]=source
                    active.remove(c)
                    signature=(c,assignment[c][0],tuple(sorted(inputs.items())))
                    name=cache.get(signature)
                    if name is None:
                        name='sbeco_joint_'+hashlib.sha256(repr(signature).encode()).hexdigest()[:20]
                        aux[name]=dict(key=c+'/O',slr=assignment[c][0],x=assignment[c][1],y=assignment[c][2])
                        newcache[signature]=name
                        for pin,source in inputs.items():links[name+'/'+pin]=source
                    mapping[c]=name
                    return name+'/O'
                dsource = clone(root) if root in edited else row['driver']
                links[row['replica']+'/D']=dsource
                for pin,e in inv.edges[cell].items():
                    if pin!='D':links[row['replica']+'/'+pin]=row.get('control_drivers',{}).get(pin,e['key'])
                if len(result['aux'])+len(aux)>max_added:
                    continue
                needed=collections.Counter({(row['target'],'FF'):1})
                for item in aux.values():
                    ref=inv.cells[item['key'].rsplit('/',1)[0]]['ref']
                    needed[item['slr'],'LUT' if ref.startswith('LUT') else ref]+=1
                capacity=getattr(inv,'capacity',{})
                if any(k in capacity and resources.get(k,0)+n>capacity[k] for k,n in needed.items()):
                    continue
                counts=dict(projected)
                detached=int(row.get('detached_loads',row['loads']))
                if detached<0 or detached>counts.get(row['key'],0):
                    raise ValueError('invalid_detached_loads')
                counts[row['key']]-=detached
                counts[row['replica']+'/Q']=int(row['loads'])
                for source in links.values():
                    if source in counts or source.startswith('sbeco_'):
                        counts[source]=counts.get(source,0)+1
                if any(v>=100 for k,v in counts.items() if v!=projected.get(k,0)):
                    continue
                admitted=(mode,predicted,aux,links,newcache,counts,needed)
                break
            if admitted is None:
                raise ValueError('shared_fanout_or_resource_budget')
            mode,predicted,aux,links,newcache,projected,needed=admitted
            for k,n in needed.items():resources[k]=resources.get(k,0)+n
            cache.update(newcache);result['aux'].update(aux);result['links'].update(links)
            result['keep'].append(ident)
            result['hints'][row['replica']]=dict(slr=target[0],x=target[1],y=target[2])
            result['hints'].update({name:{k:item[k] for k in ['slr','x','y']} for name,item in aux.items()})
            result['estimates'][ident]=dict(mode=mode,predicted_D_slack=predicted,baseline_D_slack=float(dslack),added=len(aux))
            result['owners'][ident]=sorted(set([cell,*cone,*[e['source_cell'] for c in [cell,*cone] for e in inv.edges[c].values() if e['source_cell']]]))
            decision.update(status='selected',**result['estimates'][ident])
        except (ValueError,KeyError) as error:
            decision['status']=str(error)
        result['decisions'].append(decision)
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('folder',type=Path)
    ap.add_argument('--margin',type=float,default=.2);ap.add_argument('--exclude',type=Path)
    ap.add_argument('--max-added',type=int,default=8192);ap.add_argument('--per-endpoint',type=int,default=512)
    args=ap.parse_args()
    excluded=json.loads(args.exclude.read_text()) if args.exclude else []
    if args.margin<0 or args.max_added<0 or args.per_endpoint<0:ap.error('Negative planning budget')
    plan=build(Inventory(args.folder),margin=args.margin,excluded=excluded,max_added=args.max_added,per_endpoint=args.per_endpoint)
    (args.folder/'joint_candidates.json').write_text(json.dumps(plan,indent=2)+'\n')
    if os.environ.get('JI_EXPECTED_PLAN'):
        verify_expected_plan(plan,os.environ['JI_EXPECTED_PLAN'],args.folder/'candidate_identity.json')
    with (args.folder/'joint_plan.tcl').open('w') as stream:
        for key in ['keep','aux','links','hints']:
            stream.write('set ji_'+key+' '+word(tcl(plan[key]))+'\n')
    print(json.dumps(dict(candidates=len(plan['decisions']),accepted=len(plan['keep']),aux=len(plan['aux']))))


if __name__=='__main__':main()
