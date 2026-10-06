"""Discover bounded control attachments without absorbing shared control trees."""
from collections import Counter, defaultdict
import re

from control_path_cost import COMB


def discover(data, feedback, joint, protected, owners, cfg):
    protected_atoms={a for unit in protected for a in unit['atoms']}
    scope_owner={}
    for unit in joint:
        scope=unit['hierarchy'].split('/@joint_')[0]
        targets={owners[c] for a in unit['atoms'] for c in data['atoms'][a]}
        if len(targets)!=1: raise ValueError('Protected joint chain is split')
        scope_owner.setdefault(scope,set()).update(targets)
    scopes=sorted(scope_owner,key=len,reverse=True)
    pattern=re.compile(cfg['control_name_pattern'])
    shells=defaultdict(set); shell_ranks=defaultdict(set); control=[]
    for path in feedback['paths']:
        if not (pattern.search(path['source']) or pattern.search(path['sink'])): continue
        control.append(path)
        source=path['cells'][0]
        scope=next((s for s in scopes if source.startswith(s+'/')),None)
        if scope is None or len(scope_owner[scope])!=1: continue
        for c in path['cell_ids']:
            name=data['cells'][c]['cell_name']; a=data['atom_of'][c]
            if not name.startswith(scope+'/'): break
            if a<0 or a in protected_atoms: break
            shells[scope].add(a); shell_ranks[scope].add(path['rank'])
    proposals=[]; occupied=set(); rejected=[]
    for scope,atoms in sorted(shells.items()):
        cells={c for a in atoms for c in data['atoms'][a]}
        if len(cells)>cfg['max_control_unit_cells'] or atoms & occupied:
            rejected.append(dict(kind='local_shell',scope=scope,cells=len(cells))); continue
        proposals.append(dict(kind='local_shell',scope=scope,atoms=sorted(atoms),
            preferred=next(iter(scope_owner[scope])),ranks=sorted(shell_ranks[scope])))
        occupied.update(atoms)
    # Shared atoms with different destination owners remain separate. They are
    # never unioned across every fanout cone or used to pull endpoints together.
    targets=defaultdict(set); evidence=defaultdict(set)
    for path in control:
        target=owners[path['cell_ids'][-1]]
        for c in reversed(path['cell_ids'][1:-1]):
            a=data['atom_of'][c]
            if a<0 or a in protected_atoms or a in occupied: break
            if not COMB.fullmatch(data['cells'][c]['primitive']): break
            targets[a].add(target); evidence[a].add(path['rank'])
    grouped=defaultdict(set)
    for a,values in targets.items():
        if len(values)==1: grouped[next(iter(values))].add(a)
    for target,atoms in sorted(grouped.items()):
        # Disconnected cones remain separate even when their endpoint owner is
        # the same. Only direct original edges join the movable interiors.
        parent={a:a for a in atoms}
        def find(a):
            while parent[a]!=a: parent[a]=parent[parent[a]]; a=parent[a]
            return a
        for _,driver,sinks,_ in data['nets']:
            a=data['atom_of'][driver] if isinstance(driver,int) else -1
            if a not in atoms: continue
            for sink in sinks:
                b=data['atom_of'][sink] if isinstance(sink,int) else -1
                if b in atoms: parent[find(b)]=find(a)
        components=defaultdict(set)
        for a in atoms: components[find(a)].add(a)
        for aa in components.values():
            cells={c for a in aa for c in data['atoms'][a]}
            if len(cells)>cfg['max_control_unit_cells']:
                rejected.append(dict(kind='capture_cone',target=target,cells=len(cells))); continue
            proposals.append(dict(kind='capture_cone',atoms=sorted(aa),preferred=target,
                ranks=sorted(set().union(*(evidence[a] for a in aa)))))
            occupied.update(aa)
    for i,p in enumerate(proposals):
        p['id']=f'CTRL{i:04d}'
        p['cells']=sorted(c for a in p['atoms'] for c in data['atoms'][a])
        p['original_owners']=dict(Counter(owners[c] for c in p['cells']))
        p['options']=list(dict.fromkeys([p['preferred'],*sorted(p['original_owners'])]))
    assert sum(len(p['atoms']) for p in proposals)==len(occupied)
    return dict(units=proposals,rejected=rejected,control_path_count=len(control),
                shared_atoms_retained=sum(len(v)>1 for v in targets.values()),
                scope='Bounded attachments identified from validated timing controls and original connectivity; no hard hierarchy merge.')
