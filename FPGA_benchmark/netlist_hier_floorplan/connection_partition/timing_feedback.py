"""Bind routed timing feedback to the unchanged post-opt partition atoms."""
import csv
import re
from collections import Counter

from balanced_physical import atom_resource
from timing_model import criticality


def table(path):
    with path.open() as f:return list(csv.DictReader(f,delimiter='\t'))


def build_feedback(data, labels, diagnostic, cfg):
    names={c['cell_name']:i for i,c in enumerate(data['cells'])}
    live={r['cell']:r for r in table(diagnostic/'native/cells.tsv')}
    routes=table(diagnostic/'native/paths.tsv')
    nodes={};mapping={};excluded={};methods=Counter()
    def convert(name):
        if name in mapping:return mapping[name]['atom']
        if name in excluded:return None
        row=live[name]
        if name.startswith('f96_identity_') or row['primitive'].startswith('BUFG'):
            excluded[name]=dict(reason='Inserted fanout or global distribution primitive projected out',primitive=row['primitive'])
            return None
        candidates=[name]
        origin=row.get('orig_cell_name','')
        if origin:
            if '/' in name:candidates.append(name.rsplit('/',1)[0]+'/'+origin)
            candidates.append(origin)
        candidates.append(re.sub(r'(?:_rep__\d+|_replica(?:_\d+)?)$','',name))
        selected=None
        for original in candidates:
            if original not in names:continue
            c=names[original];a=data['atom_of'][c]
            if a<0:continue
            mid=f'S{labels[a]:02d}'
            if mid!=row['module']:continue
            selected=(original,c,a,mid);break
        if selected is None:raise ValueError(f'Cannot bind routed cell to original module: {name}')
        original,c,a,mid=selected;method='EXACT' if original==name else 'ORIGIN_RESOLVED'
        nodes[str(a)]=dict(module=mid,resource=atom_resource(data['atom_resources'][a]),representative_cell=original)
        mapping[name]=dict(original=original,cell_id=f'c{c}',atom=a,module=mid,method=method)
        methods[method]+=1
        return a

    paths={};edges={};projection=[]
    for row in routes:
        assert abs(float(row['requirement'])-10.)<1e-8
        pins=[row['startpoint']]+row['pins'].split('|')+[row['endpoint']]
        chain=[];live_chain=[]
        for pin in pins:
            name=pin.rsplit('/',1)[0]
            if not live_chain or live_chain[-1]!=name:live_chain.append(name)
            a=convert(name)
            if a is not None and (not chain or chain[-1]!=a):chain.append(a)
        assert chain and convert(row['startpoint'].rsplit('/',1)[0])==chain[0]
        assert convert(row['endpoint'].rsplit('/',1)[0])==chain[-1]
        slack=float(row['slack']);q=criticality(slack,cfg);key=tuple(chain)
        projection.append(dict(rank=int(row['rank']),slack_ns=slack,criticality=q,atoms=chain,live_cells=live_chain))
        if key not in paths or slack<paths[key]['slack_ns']:
            paths[key]=dict(atoms=chain,slack_ns=slack,criticality=q,representative_rank=int(row['rank']))
        for a,b in zip(chain,chain[1:]):
            edges[a,b]=max(q,edges.get((a,b),0))
    observed=len(edges)
    raw=[n for n in data['nets'] if n[0]==cfg['broadcast_net_id']]
    assert len(raw)==1
    _,driver,sinks,_=raw[0];source=data['atom_of'][driver]
    assert source>=0
    q=max(p['criticality'] for p in paths.values() if p['atoms'][0]==source)
    broadcast_sinks=[]
    for cell in [driver,*sinks]:
        a=data['atom_of'][cell];assert a>=0
        nodes[str(a)]=dict(module=f'S{labels[a]:02d}',resource=atom_resource(data['atom_resources'][a]),
                           representative_cell=data['cells'][cell]['cell_name'])
    for cell in sinks:
        a=data['atom_of'][cell];broadcast_sinks.append(a)
        if a!=source and cfg['broadcast_complete_feedback']:
            edges[source,a]=max(q,edges.get((source,a),0))
    return dict(nodes=nodes,paths=list(paths.values()),
        connections=[dict(source=a,sink=b,criticality=q) for (a,b),q in sorted(edges.items())],
        projection=projection,mapping=mapping,excluded=excluded,
        broadcast=dict(net_id=cfg['broadcast_net_id'],source=source,sinks=broadcast_sinks,propagated_criticality=q,
                       interpretation='All original sinks included; criticality conservatively propagated from the same launch BRAM, not measured at every sink.'),
        coverage=dict(native_paths=len(routes),projected_unique_paths=len(paths),mapped_cells=len(mapping),
                      mapping_methods=dict(methods),excluded_auxiliary_cells=len(excluded),
                      observed_unique_atom_connections=observed,complete_feedback_connections=len(edges),
                      added_broadcast_connections=len(edges)-observed,
                      original_broadcast_sink_pins=len(sinks)),
        limitations=['Only the frozen worst1000 timing paths are projected; not full STA coverage.',
            'Inserted identity/BUFG distribution cells are removed from the planning trace; their final topology and delay are not predicted.',
            'Native replicas map to original atoms and membership; future replica resource use is not included.',
            'Distinct atoms use independent capacity-proportional locations, including within the same module.',
            'Repeated appearances of one atom share its SLR assignment within a path.',
            'Original broadcast sinks supplement the directed cost without implying measured criticality at every sink.'])
