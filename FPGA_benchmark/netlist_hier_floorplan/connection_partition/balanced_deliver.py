"""Select auditable tradeoffs and export complete members, resources and evidence."""
import argparse
import csv
import gzip
import itertools
import json
import re
from collections import Counter
from pathlib import Path

import partition as base
from improve import load_context, labels_for, objective, digest
from balanced_physical import admissible, balanced_score


def rank(run, cfg, multiplier=1):
    if cfg.get('partition_objective')=='resource_logic_v1':
        from resource_pipeline import rank as resource_rank
        return resource_rank(run,cfg,multiplier)
    binding=json.loads((run/'binding.json').read_text());rows=[]
    for f in sorted((run/'candidates').glob('*/balanced_regions.json')):
        result=json.loads(f.read_text());summary=json.loads((f.parent/'summary.json').read_text())
        if result['status']!='feasible':continue
        actual='boundary_spatial_v1' if result.get('physical_model')=='boundary_spatial_v1' else 'all_atom_v1'
        if actual!=cfg.get('hypernet_model','all_atom_v1'):
            raise ValueError('Cannot rank candidates with different D_hyper models: '+str(f))
        metric=summary['metrics']
        score=balanced_score(result['components'],metric,binding['all_net_weight'],cfg)
        rows.append(dict(candidate=f.parent.name,**metric,**result['components'],score=score,
             feasible=True,admissible=admissible(metric,cfg,multiplier),
             total_module_crs=result['total_module_crs'],occupied_crs=result['overlap']['occupied_crs'],
             overlapping_crs=result['overlap']['overlapping_crs']))
    eligible=[r for r in rows if r['admissible']]
    if not eligible:return None,rows
    best=min(r['score'] for r in eligible)
    near=[r for r in eligible if r['score']<=best*(1+cfg['selection_relative_tolerance'])]
    selected=min(near,key=lambda r:(r['module_count'],r['weighted_km1'],r['logical_core_loss'],r['score'],r['candidate']))
    return selected,rows


def select(run):
    cfg=json.loads((run/'source/balanced_config.json').read_text())
    if cfg.get('partition_objective')=='resource_logic_v1':
        selected,rows=rank(run,cfg)
        if selected is None:raise ValueError('No admissible resource partition candidate.')
        (run/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
        (run/'selection.json').write_text(json.dumps(dict(selected=selected['candidate'],metrics=selected,
            rule='Resource-only C+L; no physical score or module-count tie-break.'),indent=2)+'\n')
        return selected['candidate']
    selected,rows=rank(run,cfg)
    assert selected
    (run/'comparison.json').write_text(json.dumps(rows,indent=2)+'\n')
    fields=['candidate','module_count','weighted_km1','weighted_cut','logical_core_loss','fragmented_cores',
            'core_minority_cells','physical_cost','slr_span','score','admissible','max_cells','min_cells',
            'total_module_crs','occupied_crs','overlapping_crs','global_added_fraction','maximum_local_split_fraction']
    base.write_table(run/'comparison.tsv',rows,fields)
    sensitivity=[]
    for budget,slr,cut,complexity in itertools.product((.5,1,2),(2,4,8),(1,2,4),(.00125,.0025,.005)):
        variant=dict(cfg,slr_distance_weight=slr,cut_weight=cut,module_cost_fraction_of_all_net_weight=complexity)
        chosen,_=rank(run,variant,budget)
        sensitivity.append(dict(budget_multiplier=budget,slr_weight=slr,cut_weight=cut,
            complexity_weight=complexity,selected=chosen['candidate'] if chosen else None,
            module_count=chosen['module_count'] if chosen else None))
    (run/'sensitivity.json').write_text(json.dumps(dict(scope='Re-ranking frozen region plans; not re-solving each parameter setting',
        selections=dict(Counter(r['selected'] for r in sensitivity)),runs=sensitivity),indent=2)+'\n')
    result=dict(selected=selected['candidate'],metrics=selected,
        rule='Admissible candidates; within 1% of lowest composite score prefer fewer modules, lower real km1, lower core loss, then score.',
        scope='Best among evaluated proposals under a static model; not global partition optimum or physical timing evidence.')
    (run/'selection.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return selected['candidate']


def deliver(run,name,output_subdir='selected',id_prefix='B'):
    cfg=json.loads((run/'source/balanced_config.json').read_text())
    resource_only=cfg.get('partition_objective')=='resource_logic_v1'
    if resource_only:
        import pickle
        with (run/'graph.pkl').open('rb') as stream:data=pickle.load(stream)
        reference=json.loads((run/'baseline/final/modules.json').read_text())
        assert digest(reference['input_dcp'])==reference['input_sha256']
    else:
        data,_,baseline,reference=load_context(run)
    folder=run/'candidates'/name
    s=json.loads((folder/'summary.json').read_text())
    regions=None if resource_only else json.loads((folder/'balanced_regions.json').read_text())
    groups=json.loads((folder/'groups.json').read_text());labels=labels_for(data,groups)
    from joint_units import load_protection, require_intact, export_protection
    protected,joint,protection_manifest=load_protection(run.parent) if resource_only else ([],[],None)
    if protection_manifest:
        require_intact(labels,protected,'delivery admission')
    km1,cut=objective(data['edges'],labels)
    owner,modules,pairs,ports,metrics=base.summaries(data,dict(groups=groups,membership=labels,weighted_km1=km1,weighted_cut=cut))
    assert metrics['weighted_km1']==s['metrics']['weighted_km1']
    mapping={m['module_id']:f'{id_prefix}{i:02d}' for i,m in enumerate(modules)}
    out=run/output_subdir;out.mkdir(parents=True)
    if protection_manifest:
        s['protection']=export_protection(out,data,labels,protected,joint,
            [mapping[m['module_id']] for m in modules],protection_manifest)
    counts=Counter();totals=Counter()
    with gzip.open(out/'leaf_cells.tsv.gz','wt') as f:
        fields=['cell_id','cell_name','primitive','original_hierarchy','module_id',*base.RESOURCES]
        writer=csv.DictWriter(f,fieldnames=fields,delimiter='\t');writer.writeheader()
        for i,(cell,mid) in enumerate(zip(data['cells'],owner)):
            assert cell['cell_id']==f'c{i}'
            resources=base.resources(cell['primitive']);mid=mapping.get(mid,mid)
            counts[mid]+=1;totals.update(resources)
            writer.writerow(dict(cell,module_id=mid,**{r:resources.get(r,0) for r in base.RESOURCES}))
    volume=Counter();internal=Counter()
    for edge,w in data['edges']:
        touched={labels[a] for a in edge}
        for m in touched:volume[m]+=w/4
        if len(touched)==1:internal[next(iter(touched))]+=w/4
    profiles=[]
    for i,(module,group) in enumerate(zip(s['modules'],groups)):
        old=module['module_id'];module['module_id']=mapping[old];module['candidate_module_id']=old
        module['internal_net_weight']=internal[i];module['incident_net_weight']=volume[i]
        module['internal_incident_ratio']=internal[i]/volume[i] if volume[i] else 0
        assert module['cells']==counts[module['module_id']]
        hierarchy=Counter();top=Counter()
        for a in group:
            for c in data['atoms'][a]:
                row=data['cells'][c];h=row['original_hierarchy'];hierarchy[h]+=1
                if h=='TOP':
                    stem=re.sub(r'\[[^\]]*\]','[]',row['cell_name'])
                    stem=re.sub(r'_i_\d+.*$','_logic',stem)
                    top[stem]+=1
        profiles.append(dict(module_id=module['module_id'],dominant_exact_hierarchies=hierarchy.most_common(12),
                             top_direct_name_families=top.most_common(8),
                             interpretation='Provenance and naming evidence only; functional semantics are not proved.'))
    for r in base.RESOURCES:assert sum(m[r] for m in s['modules'])==totals[r]==data['totals'].get(r,0)
    assert sum(counts.values())==len(data['cells'])
    connections=[dict(source=mapping[a],sink=mapping[b],**dict(p)) for (a,b),p in sorted(pairs.items())]
    portrows=[dict(source=mapping.get(a,a),sink=mapping.get(b,b),**dict(v)) for (a,b),v in sorted(ports.items())]
    base.write_table(out/'module_resources.tsv',s['modules'],['module_id','cells',*base.RESOURCES,
        'top_direct_cells','floorplan_eligible','internal_incident_ratio','internal_net_weight','incident_net_weight']+
        (['equivalent_crs','below_soft_minimum'] if resource_only else []))
    base.write_table(out/'module_connections.tsv',connections,['source','sink','nets','sink_pin_connections','weighted_nets','data_nets','control_nets'])
    base.write_table(out/'port_connections.tsv',portrows,['source','sink','nets','sink_pin_connections'])
    (out/'logical_profiles.json').write_text(json.dumps(profiles,indent=2)+'\n')
    if regions is not None:
        regions['regions']={mapping[m]:r for m,r in regions['regions'].items()}
        regions['candidate_stats']={mapping[m]:v for m,v in regions['candidate_stats'].items()}
        for row in regions['overlap']['contributions']:row['modules']=[mapping[m] for m in row['modules']]
        (out/'static_regions.json').write_text(json.dumps(regions,indent=2)+'\n')
    else:
        audit=json.loads((folder/'resource_evaluation.json').read_text())
        assert audit['audit']['valid']
        for row in audit['audit']['modules']:row['module_id']=mapping[row['module_id']]
        (out/'resource_evaluation.json').write_text(json.dumps(audit,indent=2)+'\n')
        s['partition_objective']=dict(schema='resource_logic_v1',score=audit['score'],
            formula='cut_weight*C + logical_core_weight*L',cut_weight=cfg['cut_weight'],
            logical_core_weight=cfg['logical_core_weight'],positions_assigned=False)
    s.update(input_dcp=reference['input_dcp'],input_sha256=reference['input_sha256'],selected_candidate=name,
             connections=connections,infrastructure={k:v for k,v in counts.items() if k not in mapping.values()},
             validation=dict(all_cells=len(data['cells']),unique_ordered_ids=True,resources_conserved=True,
                             dedicated_atoms_preserved=True,graph_sha256=digest(run/'graph.pkl')),
             physical_validation=('Anonymous single-die capacity check only; no position or physical feasibility proof.'
                                  if resource_only else 'Static resource/connection model only; no new placement or routing.'))
    (out/'modules.json').write_text(json.dumps(s,indent=2)+'\n')
    print(json.dumps(dict(delivered=name,modules=len(groups),ownership=counts)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['select','deliver']);p.add_argument('run',type=Path)
    p.add_argument('--candidate');p.add_argument('--output-subdir',default='selected')
    p.add_argument('--id-prefix',default='B');a=p.parse_args()
    if a.action=='select':select(a.run)
    else:deliver(a.run,a.candidate or json.loads((a.run/'selection.json').read_text())['selected'],a.output_subdir,a.id_prefix)
