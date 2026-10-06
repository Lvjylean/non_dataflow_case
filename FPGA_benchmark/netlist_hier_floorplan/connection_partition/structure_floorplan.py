"""Build a directed floorplan from expanded original-atom membership only."""
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
import time

from improve import digest, labels_for


def load(path):
    return json.loads(Path(path).read_text())


def dump(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n')


def seed_regions(meta,model,device,cfg):
    """Former partition-region initializer, now strictly after membership freezes."""
    from balanced_regions import options_for, initialize, polish
    from static_regions import all_rectangles, overlap_audit, LIMITS
    rectangles=all_rectangles(device)
    from cumulative_paths import settings
    if settings(cfg):rectangles=[r for r in rectangles if len(r['slrs'])==1]
    options={};stats={}
    for m in meta['modules']:
        mid=m['module_id']
        options[mid],stats[mid]=options_for(m,rectangles,cfg)
    if any(not values for values in options.values()):
        raise ValueError('Partition passed aggregate resource bounds but a module has no feasible CR rectangle.')
    # The shared scorer uses Pxx labels internally; public module IDs remain Sxx.
    class ModelIDs:
        def components(self,chosen,slr_weight):
            return model.components({f'P{i:02d}':chosen[m['module_id']]
                                     for i,m in enumerate(meta['modules'])},slr_weight)
        def internal_region_cost(self,*args):
            return model.internal_region_cost(*args)
    adapter=ModelIDs()
    chosen,detail,unary=initialize(meta['modules'],meta['connections'],options,adapter,device,cfg)
    if chosen is None:
        raise RuntimeError('No floorplan initialization found within search budget; partition remains intact. '+str(detail))
    chosen,components,history=polish(chosen,meta['modules'],options,adapter,device,cfg,unary)
    audit=overlap_audit(meta['modules'],chosen,device)
    assert audit['valid']
    return dict(status='feasible',regions=chosen,candidate_stats=stats,components=components,
        overlap=audit,initialization=detail,local_search=history,limits=LIMITS,
        objective=components['physical_cost']+meta['partition_objective']['score'],
        total_module_crs=sum(r['area'] for r in chosen.values()),
        physical_model=cfg.get('hypernet_model','all_atom_v1'),
        stage='floorplan_only_after_partition_selection')


def prepare(root,macro_timing=None):
    from balanced_physical import atom_resource
    from physical_model import build as build_physical_model
    from static_regions import load_device, RESOURCES, LIMITS
    from edge_padding import POLICY
    meta=load(root/'balanced/selected/modules.json')
    name=meta['selected_candidate']
    groups=load(root/'balanced/candidates'/name/'groups.json')
    with (root/'graph.pkl').open('rb') as stream:data=pickle.load(stream)
    labels=labels_for(data,groups)
    from joint_units import load_protection, require_intact
    protected,_,protection_manifest=load_protection(root)
    if protection_manifest:
        require_intact(labels,protected,'floorplan input')
    assert len(labels)==len(data['atoms'])
    assert all(m['floorplan_eligible'] for m in meta['modules'])
    cfg=load(root/'source/directed_config.json')
    assert cfg['resource_limits']==LIMITS
    assert cfg['soft_expansion_threshold']==POLICY['threshold']
    assert not cfg.get('routed_density_profile')
    from cumulative_paths import settings
    from macro_timing import macros, read as read_macros
    if settings(cfg) and settings(cfg)['topology_model']=='macro_timing_v2' and macros(data):
        macro_timing=Path(macro_timing) if macro_timing else root/'macro_timing'
        read_macros(macro_timing,digest(root/'graph.pkl'),meta['input_sha256'])
    run=root/'floorplan'
    run.mkdir()
    shutil.copytree(root/'source',run/'source',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(root/'balanced/selected',run/'input/export')
    shutil.copy2(root/'cr.tsv',run/'input/cr.tsv')
    device=load_device(root/'cr.tsv')
    model=build_physical_model(data,labels,len(groups),device,cfg)
    if meta.get('partition_objective',{}).get('schema')=='resource_logic_v1':
        initial_cfg=dict(load(root/'source/balanced_config.json'))
        # Physical seeding adopts the unchanged downstream resource/SLR settings.
        initial_cfg.update({k:v for k,v in cfg.items() if k in initial_cfg})
        if 'cumulative_paths' in cfg:initial_cfg['cumulative_paths']=cfg['cumulative_paths']
        static=seed_regions(meta,model,device,initial_cfg)
        dump(run/'input/export/static_regions.json',static)
    else:
        static=load(root/'balanced/selected/static_regions.json')
    dump(run/'input/original_regions.json',static)
    with (run/'netmodel.pkl').open('wb') as f:
        pickle.dump(model,f,protocol=4)
    slots=[labels[a]*len(RESOURCES)+RESOURCES.index(atom_resource(r))
           for a,r in enumerate(data['atom_resources'])]
    weights,counts,coverage=Counter(),Counter(),Counter()
    for _,driver,sinks,w in data['nets']:
        coverage['signal_nets']+=1
        coverage['signal_sink_pins']+=len(sinks)
        if not isinstance(driver,int):
            coverage['unlocated_port_source_pins']+=len(sinks)
            continue
        a=data['atom_of'][driver]
        if a<0:
            coverage['unlocated_infrastructure_source_pins']+=len(sinks)
            continue
        modeled=False
        for sink in sinks:
            if not isinstance(sink,int):
                coverage['unlocated_port_sink_pins']+=1
                continue
            b=data['atom_of'][sink]
            if b<0:
                coverage['unlocated_infrastructure_sink_pins']+=1
                continue
            modeled=True
            coverage['modeled_sink_pins']+=1
            coverage['data_pins' if w==4 else 'control_pins']+=1
            if a==b:
                coverage['same_atom_pins']+=1
                continue
            pair=slots[a],slots[b]
            weights[pair]+=w/4
            counts[pair]+=1
            coverage['distinct_atom_pins']+=1
            coverage['internal_module_pins' if labels[a]==labels[b] else 'inter_module_pins']+=1
        coverage['nets_with_modeled_pins']+=int(modeled)
    assert coverage['modeled_sink_pins']==coverage['same_atom_pins']+coverage['distinct_atom_pins']
    assert coverage['signal_sink_pins']==coverage['modeled_sink_pins']+sum(coverage[k] for k in (
        'unlocated_port_source_pins','unlocated_port_sink_pins',
        'unlocated_infrastructure_source_pins','unlocated_infrastructure_sink_pins'))
    from boundary_directed import attach
    if hasattr(model,'directed_data'):
        model.directed_data['binding']=dict(graph_sha256=digest(root/'graph.pkl'),
            membership_sha256=digest(run/'input/export/leaf_cells.tsv.gz'),
            module_ids=[m['module_id'] for m in meta['modules']])
    dump(run/'directed.json',attach(dict(module_count=len(groups),coverage=dict(coverage),families={},
        pairs=[dict(source=a,sink=b,weight=w,pins=counts[a,b]) for (a,b),w in sorted(weights.items())],
        semantics='Original atom sink-pin multiplicity for branch risks; spatial distance uses the explicitly selected model.'),model,cfg))
    dump(run/'binding.json',dict(input_dcp=meta['input_dcp'],input_sha256=meta['input_sha256'],
        graph_sha256=digest(root/'graph.pkl'),module_count=len(groups),
        fixed_partition_cost=static['objective']-static['components']['physical_cost'],
        hypernet_model=cfg.get('hypernet_model','all_atom_v1')))
    from cumulative_paths import settings
    from path_cache import write as write_paths, FILES
    if settings(cfg):write_paths(run,data,labels,[m['module_id'] for m in meta['modules']],digest(root/'graph.pkl'),macro_timing)
    dump(run/'hypernet_audit.json',getattr(model,'audit',{}))
    dump(run/'search_references.json',[dict(name='partition',path='input/export/static_regions.json')])
    files=[p for p in (run/'input').rglob('*') if p.is_file()]
    files += [run/n for n in ['netmodel.pkl','directed.json','search_references.json']]
    if settings(cfg):files += [run/n for n in FILES]
    dump(run/'local_binding.json',dict(source_sha256={str(p.relative_to(run)):digest(p) for p in files},
                                     scope='New expanded membership on immutable original netlist.'))
    dump(run/'source/manifest.json',{p.name:digest(p) for p in (run/'source').iterdir()
                                    if p.is_file() and p.name!='manifest.json'})
    dump(run/'preparation.json',dict(status='PASS',coverage=dict(coverage),module_count=len(groups)))
    return run


def implementation_input(root,run):
    from partition import RESOURCES
    out=root/'implementation_input'
    out.mkdir()
    shutil.copytree(run/'export',out/'export')
    for name in ['regions.tcl','soft_region_adapter.tcl','edge_padding.json']:
        shutil.copy2(run/'soft'/name,out/name)
    shutil.copy2(run/'solution.json',out/'core_solution.json')
    meta=load(out/'export/modules.json')
    assert digest(Path(meta['input_dcp']))==meta['input_sha256']
    expected={m['module_id']:m for m in meta['modules']}
    counts=Counter()
    resources={m:Counter() for m in expected}
    with gzip.open(out/'export/leaf_cells.tsv.gz','rt') as f, (out/'membership.tsv').open('w') as stream:
        writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
        writer.writerow(['cell','module','resource','ref'])
        for i,row in enumerate(csv.DictReader(f,delimiter='\t')):
            assert row['cell_id']==f'c{i}'
            m=row['module_id'];counts[m]+=1
            rr={r:int(row[r]) for r in RESOURCES}
            if m in resources:
                resources[m].update(rr)
            resource=next((r for r in ('DSP','URAM','BRAM18','FF','LUT','CARRY8','MUXF8','MUXF7') if rr[r]),'OTHER')
            writer.writerow([row['cell_name'],m,resource,row['primitive']])
    assert sum(counts.values())==meta['validation']['all_cells']
    for m,v in expected.items():
        assert counts[m]==v['cells']
        assert all(resources[m][r]==v[r] for r in RESOURCES)
    dump(out/'manifest.json',dict(status='PASS',input_dcp=meta['input_dcp'],input_sha256=meta['input_sha256'],
        module_count=len(expected),counts=dict(counts),
        files={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()},
        scope='Expanded leaf membership with core-resource accounting and geometric soft extensions. No P&R.'))


def finish(root, chain_guidance=False):
    from floorplan_cached import export
    run=prepare(root)
    for name in ['fixed11_search','fixed11_explore','fixed11_verify']:
        start=time.monotonic()
        with (run/(name+'.log')).open('w') as log:
            subprocess.run([sys.executable,'-B','-u',str(run/'source'/(name+'.py')),str(run)],
                           stdout=log,stderr=subprocess.STDOUT,check=True)
        dump(run/(name+'.status.json'),dict(status='PASS',seconds=time.monotonic()-start))
    export(run)
    implementation_input(root,run)
    assert load(run/'verification.json')['status']=='PASS'
    if chain_guidance:
        from chain_guidance import run as guide
        guide(root, root/'chain_guidance')
