"""Export repaired memberships and independently verify static input contracts."""
from collections import Counter
import csv
from fractions import Fraction
import gzip
import json
from pathlib import Path
import shutil

import numpy as np

import partition as base
from improve import digest, objective
from joint_units import export_protection
from edge_padding import expand, regions_tcl, region_from_crs
from static_regions import RESOURCES, overlap_audit


def dump(path,value): Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def export_table(out,data,owner_names,ids,protected,joint,protection_manifest):
    out.mkdir();index={m:i for i,m in enumerate(ids)}
    labels=[index[owner_names[g[0]]] for g in data['atoms']]
    groups=[[] for _ in ids]
    for a,m in enumerate(labels):groups[m].append(a)
    assert all(groups)
    km1,cut=objective(data['edges'],labels)
    _,modules,pairs,ports,metrics=base.summaries(data,dict(groups=groups,membership=labels,
                                                       weighted_km1=km1,weighted_cut=cut))
    rename={f'P{i:02d}':m for i,m in enumerate(ids)}
    for m in modules:m['module_id']=rename[m['module_id']]
    connections=[dict(source=rename.get(a,a),sink=rename.get(b,b),**dict(v)) for (a,b),v in sorted(pairs.items())]
    portrows=[dict(source=rename.get(a,a),sink=rename.get(b,b),**dict(v)) for (a,b),v in sorted(ports.items())]
    fields=['cell_id','cell_name','primitive','original_hierarchy','module_id',*RESOURCES]
    with gzip.open(out/'leaf_cells.tsv.gz','wt') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t');w.writeheader()
        for c,m in zip(data['cells'],owner_names):
            q=base.resources(c['primitive'])
            w.writerow(dict(c,module_id=m,**{r:q.get(r,0) for r in RESOURCES}))
    base.write_table(out/'module_connections.tsv',connections,
                     ['source','sink','nets','sink_pin_connections','weighted_nets','data_nets','control_nets'])
    base.write_table(out/'port_connections.tsv',portrows,['source','sink','nets','sink_pin_connections'])
    protection=export_protection(out,data,labels,protected,joint,ids,protection_manifest)
    return modules,connections,metrics,protection


def export_and_verify(out,root,old,data,model,old_meta,old_core,protected,joint,protection_manifest,before,after,cfg):
    impl=out/'implementation_input';impl.mkdir()
    modules,connections,metrics,certificate=export_table(impl/'export',data,model.owners,model.ids,protected,joint,protection_manifest)
    parent_of=model.parent_of
    logical_owners=[parent_of.get(m,m) for m in model.owners]
    logical_ids=sorted(set(parent_of.values()))
    lm,lc,lmetrics,lcert=export_table(impl/'logical_export',data,logical_owners,logical_ids,protected,joint,protection_manifest)
    joint_counts=Counter(model.labels[u['atoms'][0]] for u in joint)
    for m in modules:
        m.update(logical_parent=parent_of[m['module_id']],chain_count=joint_counts[m['module_id']])
        assert m['cells']==model.cells[m['module_id']]
        assert all(m[r]==model.demands[m['module_id']][r] for r in RESOURCES)
    for folder,rows in [('export',modules),('logical_export',lm)]:
        base.write_table(impl/folder/'module_resources.tsv',rows,
                        ['module_id','logical_parent','cells','chain_count',*RESOURCES,'floorplan_eligible'])
    counts=Counter(model.owners)
    with (impl/'membership.tsv').open('w') as f:
        writer=csv.writer(f,delimiter='\t',lineterminator='\n');writer.writerow(['cell','module','resource','ref'])
        for cell,mid in zip(data['cells'],model.owners):
            q=base.resources(cell['primitive'])
            resource=next((r for r in ('DSP','URAM','BRAM18','FF','LUT','CARRY8','MUXF8','MUXF7') if q.get(r)), 'OTHER')
            writer.writerow([cell['cell_name'],mid,resource,cell['primitive']])
    audit=overlap_audit(modules,model.regions,model.device,model.limits)
    core=dict(status='feasible',regions=model.regions,overlap=audit,limits=model.limits,
        objective=after['J_control'],components={k:v for k,v in after.items() if k!='observed_paths'},
        objective_role='C+L plus existing directed cost and cumulative register-bounded path penalty. D_hyper is not part of this optional local refinement objective.')
    proposed,padding=expand(modules,core,model.device)
    old_padding=json.loads((old/'edge_padding.json').read_text())['actual_padding']
    soft={}
    for mid,region in model.regions.items():
        unchanged=set(region['crs'])==set(old_core['regions'][mid]['crs'])
        crs=set(region['crs'])|set(old_padding[mid]) if unchanged else set(proposed[mid]['crs'])
        s=region_from_crs(crs,model.device);s.pop('capacity')
        s.update(core_crs=region['crs'],padding_crs=sorted(crs-set(region['crs'])),geometry_role='soft_allowance_only')
        soft[mid]=s
    (impl/'regions.tcl').write_text(regions_tcl(soft))
    shutil.copy2(old/'soft_region_adapter.tcl',impl/'soft_region_adapter.tcl')
    dump(impl/'edge_padding.json',dict(proposals=padding,actual_padding={m:r['padding_crs'] for m,r in soft.items()},
        scope='Core capacity only. Preserve unchanged core envelopes; moved small modules use existing shared edge50 expansion.'))
    dump(impl/'core_solution.json',core);dump(impl/'export/static_regions.json',core)
    dump(impl/'physical_to_logical.json',parent_of)
    dump(impl/'chain_groups.json',{u['hierarchy']:model.labels[u['atoms'][0]] for u in joint})
    meta=dict(old_meta,modules=modules,connections=connections,
        logical_partition=dict(module_count=len(lm),unchanged=False,objective={k:after[k] for k in ('C','L','J_partition')},export='logical_export'),
        physical_group_metrics=metrics,
        validation=dict(all_cells=len(data['cells']),resources_conserved=True,protection=certificate),
        refinement=dict(schema=cfg['schema'],baseline_input=str(old),netlist_unchanged=True))
    dump(impl/'export/modules.json',meta)
    dump(impl/'logical_export/modules.json',dict(modules=lm,connections=lc,metrics=lmetrics,
        partition_objective={k:after[k] for k in ('C','L','J_partition')},validation=dict(all_cells=len(data['cells']),protection=lcert),
        input_dcp=meta['input_dcp'],input_sha256=meta['input_sha256']))
    dump(impl/'manifest.json',dict(status='PASS',input_dcp=meta['input_dcp'],input_sha256=meta['input_sha256'],
        module_count=len(modules),logical_module_count=len(lm),counts=dict(counts),logical_membership_preserved=False,
        protection=certificate,files={str(p.relative_to(impl)):digest(p) for p in impl.rglob('*') if p.is_file()},
        scope='Control-cone membership and small control region refinement. Protected data chains and memory/DSP regions unchanged. No P&R.'))
    result=verify(out,old,data,model,modules,protected,joint,before,after)
    summary=dict(status='PASS',schema=cfg['schema'],logical_module_count=len(lm),physical_group_count=len(modules),
        modules=modules,parent_of=parent_of,core_plan=core,soft_regions=soft,
        changed_cells=sum(a!=b for a,b in zip(model.original_owners,model.owners)),
        changed_logical_cells=sum(parent_of.get(a,a)!=parent_of.get(b,b) for a,b in zip(model.original_owners,model.owners)),
        moved_regions=[m for m in model.ids if model.regions[m]['bounds']!=old_core['regions'][m]['bounds']],
        before={k:v for k,v in before.items() if k!='observed_paths'},after={k:v for k,v in after.items() if k!='observed_paths'},
        verification=result,actual_congestion_or_timing='UNMEASURED: no placement or routing.',
        comparison_titles=['B: original physical groups','C: control cones + cumulative path cost'],
        figure_title='Memory/compute regions retained; control membership and small regions refined')
    dump(out/'summary.json',summary)
    from chain_guidance_plot import plots
    plots(out,old_core,model.device)
    return summary


def verify(out,old,data,model,modules,protected,joint,before,after):
    """Recount export cells, rational capacity and original directed branches."""
    impl=out/'implementation_input';counts=Counter();demands={m:Counter() for m in model.ids}
    exported=[];names=set()
    with gzip.open(impl/'export/leaf_cells.tsv.gz','rt') as f:
        for i,row in enumerate(csv.DictReader(f,delimiter='\t')):
            source=data['cells'][i]
            assert all(row[k]==source[k] for k in ('cell_id','cell_name','primitive','original_hierarchy'))
            assert row['cell_name'] not in names;names.add(row['cell_name'])
            mid=row['module_id'];exported.append(mid);counts[mid]+=1
            q=base.resources(row['primitive'])
            assert all(int(row[r])==q.get(r,0) for r in RESOURCES)
            if mid in demands:demands[mid].update(q)
    assert exported==model.owners and len(exported)==len(data['cells'])
    with (impl/'membership.tsv').open() as f:
        row_count=0
        for i,row in enumerate(csv.DictReader(f,delimiter='\t')):
            source=data['cells'][i]
            assert row['cell']==source['cell_name'] and row['ref']==source['primitive']
            assert row['module']==exported[i]
            row_count+=1
        assert row_count==len(data['cells'])
    assert all({exported[c] for c in g}=={model.labels[a]} for a,g in enumerate(data['atoms']))
    assert all(len({model.labels[a] for a in u['atoms']})==1 for u in protected)
    assert all(model.labels[a]==model.original_owners[data['atoms'][a][0]] for u in protected for a in u['atoms'])
    assert all(m['cells']==counts[m['module_id']] and all(m[r]==demands[m['module_id']][r] for r in RESOURCES) for m in modules)
    assert all(sum(q[r] for q in demands.values())==data['totals'].get(r,0) for r in RESOURCES)
    usage={c:{r:Fraction(0) for r in RESOURCES} for c in model.device}
    for mid,q in demands.items():
        region=model.regions[mid]
        for r in RESOURCES:
            cap=sum(model.device[c]['resources'][r] for c in region['crs'])
            assert cap==region['capacity'][r] and (cap or not q[r])
            for c in region['crs']:
                if model.device[c]['resources'][r] and q[r]:usage[c][r]+=Fraction(q[r],cap)
    assert all(v<=Fraction(str(model.limits[r])) for row in usage.values() for r,v in row.items())
    # Independent original-pin aggregation through the established directed model.
    from balanced_physical import atom_resource
    from directed_model import DirectedModel
    index={m:i for i,m in enumerate(model.ids)};weights=Counter();pins=Counter();same=0
    slots=[index[model.labels[a]]*len(RESOURCES)+RESOURCES.index(atom_resource(q)) for a,q in enumerate(data['atom_resources'])]
    for _,driver,sinks,w in data['nets']:
        a=data['atom_of'][driver] if isinstance(driver,int) else -1
        if a<0:continue
        for sink in sinks:
            b=data['atom_of'][sink] if isinstance(sink,int) else -1
            if b<0:continue
            if a==b:same+=1;continue
            weights[slots[a],slots[b]]+=w/4;pins[slots[a],slots[b]]+=1
    directed=dict(module_count=len(model.ids),families={},coverage={'same_atom_pins':same},
        pairs=[dict(source=a,sink=b,weight=w,pins=pins[a,b]) for (a,b),w in weights.items()])
    dm=DirectedModel(directed,model.device,model.branch.cfg)
    components=dm.components({f'S{i:02d}':model.regions[m] for i,m in enumerate(model.ids)})
    cost=components['directed_term']+components['branch_square_term']
    assert abs(cost-after['directed_cost'])<=max(1e-5,abs(cost)*1e-10)
    logical=[model.parent_of[m] for m in model.labels]
    assert objective(data['edges'],logical)[0]==after['C']
    assert objective(model.logical_edges,logical)[0]==after['L']
    # Scalar relaxation independently checks NumPy's simultaneous layer updates.
    slr=model.path.slrs(exported,model.regions);reach=[-1000000]*len(exported)
    for a,b in zip(*model.path.launch):
        a,b=int(a),int(b);reach[b]=max(reach[b],abs(int(slr[a])-int(slr[b])))
    for aa,bb in model.path.layers:
        for a,b in zip(aa,bb):
            a,b=int(a),int(b);reach[b]=max(reach[b],reach[a]+abs(int(slr[a])-int(slr[b])))
    endpoint={c:reach[c] for c in range(len(exported)) if model.path.reg[c] and reach[c]>=0}
    for ids,path in model.path.observed:
        n=sum(abs(int(slr[a])-int(slr[b])) for a,b in zip(ids,ids[1:]))
        t=int(ids[-1]);endpoint[t]=max(endpoint.get(t,-1),n)
    penalty=sum(model.path.weights[c]*max(0,n-1)**2 for c,n in endpoint.items())
    assert abs(penalty-after['weighted_path_square'])<1e-7
    manifest=json.loads((impl/'manifest.json').read_text())
    assert all(digest(impl/name)==h for name,h in manifest['files'].items())
    result=dict(status='PASS',leaf_cells=len(exported),unique_membership=True,resources_conserved=True,
        protected_units=len(protected),joint_chains=len(joint),protected_members_and_owners_unchanged=True,
        rational_capacity=True,maximum_utilization={r:float(max(v[r] for v in usage.values())) for r in RESOURCES},
        independent_directed_cost=cost,independent_path_square=float(penalty),logical_cut_and_core_loss=True,
        native_Vivado_binding=False,placement_or_routing=False)
    dump(out/'independent_verification.json',result)
    return result
