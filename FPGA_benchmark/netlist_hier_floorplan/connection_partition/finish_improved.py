"""Deliver a selected candidate with new IDs, preserving baseline P identifiers."""
import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path

import partition as base
from improve import digest, labels_for, load_context, objective


def main(run,name):
    data,original,baseline,reference=load_context(run)
    folder=run/'candidates'/name
    source=json.loads((folder/'summary.json').read_text())
    groups=json.loads((folder/'groups.json').read_text())
    labels=labels_for(data,groups);km1,cut=objective(data['edges'],labels)
    result=dict(groups=groups,membership=labels,weighted_km1=km1,weighted_cut=cut)
    owner,modules,pairs,ports,metrics=base.summaries(data,result)
    mapping={m['module_id']:f'N{i:02d}' for i,m in enumerate(modules)}
    modules=source['modules']
    for m in modules:
        previous=m['module_id'];m['candidate_module_id']=previous;m['module_id']=mapping[previous]
        m['dominant_baseline_parent']=max(m['baseline_parent_cells'],key=m['baseline_parent_cells'].get)
    owner=[mapping.get(m,m) for m in owner]
    out=run/'selected';out.mkdir()
    counts=Counter();totals=Counter()
    with gzip.open(out/'leaf_cells.tsv.gz','wt') as f:
        fields=['cell_id','cell_name','primitive','original_hierarchy','module_id',*base.RESOURCES]
        writer=csv.DictWriter(f,fieldnames=fields,delimiter='\t');writer.writeheader()
        for index,(row,mid) in enumerate(zip(data['cells'],owner)):
            assert row['cell_id']==f'c{index}'
            demand=base.resources(row['primitive']);counts[mid]+=1;totals.update(demand)
            writer.writerow(dict(row,module_id=mid,**{r:demand.get(r,0) for r in base.RESOURCES}))
    assert sum(counts.values())==len(data['cells'])
    for m in modules: assert m['cells']==counts[m['module_id']]
    for r in base.RESOURCES: assert sum(m[r] for m in modules)==totals[r]
    connections=[dict(source=mapping[a],sink=mapping[b],**{k:p[k] for k in
        ('nets','sink_pin_connections','weighted_nets','data_nets','control_nets')})
        for (a,b),p in sorted(pairs.items())]
    base.write_table(out/'module_resources.tsv',modules,
        ['module_id','dominant_baseline_parent','cells',*base.RESOURCES,'top_direct_cells','floorplan_eligible'])
    base.write_table(out/'module_connections.tsv',connections,
        ['source','sink','nets','sink_pin_connections','weighted_nets','data_nets','control_nets'])
    port_rows=[dict(source=mapping.get(a,a),sink=mapping.get(b,b),nets=p['nets'],
                    sink_pin_connections=p['sink_pin_connections']) for (a,b),p in sorted(ports.items())]
    base.write_table(out/'port_connections.tsv',port_rows,['source','sink','nets','sink_pin_connections'])
    static=json.loads((folder/'static_coupled_regions.json').read_text())
    assert static['status']=='feasible' and static['overlap']['valid']
    static['regions']={mapping[k]:v for k,v in static['regions'].items()}
    static['candidate_stats']={mapping[k]:v for k,v in static['candidate_stats'].items()}
    for family in static.get('family_constraints',{}).values():
        family['members']=[mapping[m] for m in family['members']]
    for c in static['overlap']['contributions']: c['modules']=[mapping[m] for m in c['modules']]
    for c in static['logical_parent_overlaps']:
        for key in ('resource_heavy','lut_dense'): c[key]=mapping[c[key]]
    (out/'static_regions.json').write_text(json.dumps(static,indent=2)+'\n')
    summary=dict(source,modules=modules,connections=connections,input_dcp=reference['input_dcp'],
        input_sha256=reference['input_sha256'],selected_candidate=name,
        infrastructure=reference['infrastructure'],module_id_mapping=mapping,
        validation=dict(leaf_cells=len(data['cells']),unique_ordered_cell_ids=True,
            dedicated_atoms_preserved=True,resources_conserved=True,
            graph_cache_sha256=digest(run/'graph.pkl'),device_map_sha256=digest(run/'cr.tsv')),
        physical_validation='Static resource model only; no new placement, routing or timing.')
    (out/'modules.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(dict(selected=name,modules=len(modules),ownership=dict(counts),metrics=metrics)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('candidate')
    a=p.parse_args();main(a.run,a.candidate)
