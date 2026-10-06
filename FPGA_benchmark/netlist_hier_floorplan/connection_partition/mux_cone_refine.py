"""Propose complete, unprotected RAM-fed MUX atoms for local reassignment.

This is an optional partition refinement, not a netlist transformation. Discovery
uses original connections and dedicated physical atoms, never routed paths or
cell-name patterns. Proposals still require exact objective and resource checks.
"""
from collections import Counter, defaultdict


def discover(data, labels, scope, protected=()):
    claimed = {a for unit in protected for a in unit['atoms']}
    candidates = set()
    skipped = Counter()
    for a, cells in enumerate(data['atoms']):
        if labels[a] not in scope:
            continue
        refs = [data['cells'][c]['primitive'] for c in cells]
        if not any(ref.startswith('MUXF') for ref in refs):
            continue
        if a in claimed:
            skipped['protected_mux_atoms'] += 1
            continue
        if not all(ref.startswith(('LUT', 'MUXF')) for ref in refs):
            skipped['non_combinational_atom'] += 1
            continue
        if data['atom_resources'][a].get('LUTMEM', 0):
            skipped['stateful_lut_atom'] += 1
            continue
        candidates.add(a)
    memory_inputs = defaultdict(set)
    outputs = defaultdict(set)
    port_outputs = set()
    for _, driver, sinks, weight in data['nets']:
        a = data['atom_of'][driver] if isinstance(driver, int) else -1
        if a < 0:
            continue
        memory = any(data['atom_resources'][a].get(r, 0) for r in ('URAM', 'BRAM18'))
        for sink in sinks:
            b = data['atom_of'][sink] if isinstance(sink, int) else -1
            if b == a:
                continue
            if a in candidates:
                if b < 0:
                    port_outputs.add(a)
                else:
                    outputs[a].add(b)
            if memory and weight == 4 and b in candidates:
                memory_inputs[b].add(a)
    proposals = []
    for a in sorted(candidates):
        # A dedicated atom is the smallest safe unit. Shared drivers outside it
        # stay in place; all its consumers are checked before assigning a target.
        if len(memory_inputs[a]) < 2:
            skipped['fewer_than_two_direct_memory_inputs'] += 1
            continue
        targets = {labels[b] for b in outputs[a]}
        if a in port_outputs or len(targets) != 1 or labels[a] in targets:
            skipped['shared_or_local_output_boundary'] += 1
            continue
        target = next(iter(targets))
        sinks = [data['cells'][c]['primitive'] for b in outputs[a] for c in data['atoms'][b]]
        if not sinks or not all(ref.startswith(('LUT', 'MUXF')) for ref in sinks):
            skipped['consumer_not_combinational_mux_stage'] += 1
            continue
        if any(data['atom_resources'][b].get('LUTMEM', 0) for b in outputs[a]):
            skipped['stateful_consumer'] += 1
            continue
        proposals.append(dict(atom=a, source=labels[a], target=target,
            cells=len(data['atoms'][a]), memory_atoms=sorted(memory_inputs[a]),
            consumer_atoms=sorted(outputs[a]), resources=data['atom_resources'][a],
            hierarchies=sorted({data['cells'][c]['original_hierarchy'] for c in data['atoms'][a]})))
    return proposals, dict(skipped)


def apply(labels, proposals, protected=()):
    from joint_units import require_intact
    require_intact(labels, protected, 'MUX refinement input')
    result = list(labels)
    claimed = {a for unit in protected for a in unit['atoms']}
    seen = set()
    for p in proposals:
        a = p['atom']
        if a in seen or a in claimed or result[a] != p['source']:
            raise ValueError('Invalid, overlapping or protected MUX proposal')
        seen.add(a)
        result[a] = p['target']
    require_intact(result, protected, 'MUX refinement candidate')
    return result


def receiver_targets(data, labels, proposals, max_nodes=4096):
    """Offer the unique first sequential consumer as another module target.

    This is a structural proposal, not a timing arc assertion. FFs and all hard
    macros stop traversal. Reconvergent outputs are deduplicated; ambiguous or
    oversized cones retain the direct-consumer proposal.
    """
    adjacency = defaultdict(set)
    for _, driver, sinks, _ in data['nets']:
        a = data['atom_of'][driver] if isinstance(driver, int) else -1
        if a < 0:
            continue
        for sink in sinks:
            b = data['atom_of'][sink] if isinstance(sink, int) else -1
            if b >= 0 and b != a:
                adjacency[a].add(b)
    output = []
    for p in proposals:
        seen=set();todo=list(p['consumer_atoms']);terminals=set();opaque=False
        while todo and len(seen)<=max_nodes:
            a=todo.pop()
            if a in seen:continue
            seen.add(a);q=data['atom_resources'][a]
            if any(q.get(r,0) for r in ('FF','DSP','BRAM18','URAM','LUTMEM')):
                terminals.add(labels[a]);continue
            if not adjacency[a]:opaque=True
            todo.extend(adjacency[a]-seen)
        target=next(iter(terminals)) if len(terminals)==1 and len(seen)<=max_nodes and not todo and not opaque else p['target']
        # Staying in the current owner is a valid proposal rejection.
        if target==p['source']:continue
        output.append(dict(p,target=target,direct_target=p['target'],
            first_boundary_modules=sorted(terminals),traversed_atoms=len(seen)))
    return output
