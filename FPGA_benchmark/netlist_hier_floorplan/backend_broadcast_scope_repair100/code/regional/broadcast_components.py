"""Pure planning for FF broadcasts hidden by identity LUT trees.

The logical terminal inventory never substitutes for a physical net's loads.
Every rewire refers to a real receiving pin. Timing and placement admission are
the caller's responsibility; this module neither edits a design nor predicts STA.
"""
from __future__ import annotations

import hashlib
import math
import re


def _cell(pin):
    return pin.rsplit('/', 1)[0]


def _pin(pin):
    return pin.rsplit('/', 1)[-1]


def _identity(cell):
    return (cell.get('ref') == 'LUT1'
            and str(cell.get('config', {}).get('INIT', '')).lower() == "2'h2")


def _editable(cell):
    return (cell.get('editable') is True
            and not any(cell.get(k) for k in
                        ('protected', 'fixed_route', 'asynchronous', 'is_clock', 'clock')))


def _ordinary(cell, pin):
    ref = cell.get('ref', '')
    if ref in {'FDRE', 'FDSE'}:
        return pin in {'D', 'CE', 'R', 'S'}
    if re.fullmatch(r'LUT[1-6]', ref):
        return re.fullmatch(r'I[0-5]', pin) is not None
    if ref in {'MUXF7', 'MUXF8', 'MUXF9'}:
        return pin in {'I0', 'I1', 'S'}
    if re.fullmatch(r'RAMB(18|36)E[12]', ref):
        return re.match(r'^(DI|DIN|DIP|ADDR|ENARDEN|ENBWREN|WEA|WEBWE|REGCE)', pin) is not None
    if ref in {'URAM288', 'URAM288_BASE'}:
        return re.match(r'^(DIN_[AB]|ADDR_[AB]|EN_[AB]|BWE_[AB]|RDB_WR_[AB])($|\[)', pin) is not None
    return False


def _inventory(cells, nets):
    """Validate canonical leaf edges once, including duplicate sink ownership."""
    physical = {}
    owner = {}
    for driver, sinks in sorted(nets.items()):
        barrier=driver.startswith(('barrier PORT:', 'barrier UNCONNECTED:', 'barrier UNDRIVEN:', 'barrier CLOCK:'))
        if not barrier and ('/' not in driver or _cell(driver) not in cells):
            raise ValueError('unknown_driver:' + driver)
        if len(sinks) != len(set(sinks)):
            raise ValueError('duplicate_net_sink:' + driver)
        physical[driver] = sorted(sinks)
        for sink in sinks:
            if sink in owner:
                raise ValueError('multiple_sink_drivers:' + sink)
            owner[sink] = driver
            c = cells.get(_cell(sink))
            # Missing cells/ports are barriers. A represented leaf must agree.
            if c is not None and c.get('inputs', {}).get(_pin(sink)) != driver:
                raise ValueError('inconsistent_input:' + sink)
    return physical, owner


def discover(cells, nets, min_effective=16):
    """Return components keyed by original FF/Q and explicit rejection reasons.

``terminals`` are first non-identity *input pins*, not transitive sequential
endpoints. A protected branch is retained as a barrier and never rewired. A
non-identity combinational input can be a terminal, but is never traversed.
"""
    if min_effective < 1:
        raise ValueError('invalid_min_effective')
    physical, _ = _inventory(cells, nets)
    components = {}
    decisions = {}
    # Each identity has exactly one input, so its reachable tree belongs to at
    # most one FF root. No timing-path enumeration is needed.
    for name, source in sorted(cells.items()):
        if source.get('ref') not in {'FDRE', 'FDSE'}:
            continue
        root = name + '/Q'
        if root not in physical:
            continue
        if not _editable(source) or not source.get('slr'):
            decisions[root] = 'unsupported_or_protected_root'
            continue
        transparent = set()
        terminals = {}
        edges = {}
        barriers = {}
        active = set()

        def visit(driver):
            if driver in active:
                raise ValueError('identity_cycle:' + driver)
            if driver in edges:
                return
            active.add(driver)
            edges[driver] = physical.get(driver, [])
            for sink in edges[driver]:
                c = cells.get(_cell(sink))
                if c is None:
                    barriers[sink] = 'missing_or_port_boundary'
                elif not _editable(c):
                    barriers[sink] = 'protected_or_uneditable_boundary'
                elif not _ordinary(c, _pin(sink)):
                    barriers[sink] = 'clock_or_unsupported_input'
                elif not c.get('slr'):
                    barriers[sink] = 'unplaced_boundary'
                elif _identity(c) and _pin(sink) == 'I0':
                    child = _cell(sink)
                    transparent.add(child)
                    visit(child + '/O')
                else:
                    terminals.setdefault(c['slr'], []).append(sink)
            active.remove(driver)

        visit(root)
        terminals = {slr: sorted(set(pins)) for slr, pins in sorted(terminals.items())}
        effective = sum(map(len, terminals.values()))
        if effective < min_effective:
            decisions[root] = 'below_effective_minimum'
            continue
        component = dict(canonical=root, root=root, root_cell=name,
                         root_slr=source['slr'], direct_fanout=len(physical[root]),
                         effective_fanout=effective, transparent=sorted(transparent),
                         terminals=terminals, edges=edges, barriers=barriers)
        components[root] = component
        decisions[root] = 'supported'
    return dict(components=components, decisions=decisions)


def _position(cells, pin):
    c = cells[_cell(pin)]
    return (float(c['x']), float(c['y']))


def _clusters(items, limit):
    """Deterministic balanced spatial partition with no group over the cap."""
    if len(items) <= limit:
        return [items]
    groups = math.ceil(len(items) / limit)
    left_groups = groups // 2
    left_count = min(left_groups * limit, max(left_groups, len(items) * left_groups // groups))
    xspan = max(i['x'] for i in items) - min(i['x'] for i in items)
    yspan = max(i['y'] for i in items) - min(i['y'] for i in items)
    axis = 'x' if xspan >= yspan else 'y'
    ordered = sorted(items, key=lambda i: (i[axis], i['pin']))
    return _clusters(ordered[:left_count], limit) + _clusters(ordered[left_count:], limit)


def plan_component(component, target_slr, replica_name, cells, nets, branch_limit=96):
    """Build a target-local output forest while retaining all original cells.

The caller creates/admit-checks the FF replica and its D/CE/R/S inputs. Clones
here are identity LUTs only. ``expected`` includes only changed old outputs and
new outputs; unchanged original nets are deliberately absent.
"""
    if not 2 <= branch_limit <= 99:
        raise ValueError('invalid_branch_limit')
    # Discovery validates the global inventory once. Candidate planning only
    # revisits this component's real edges, not the whole design per candidate.
    scoped_nets = {key: nets.get(key, []) for key in component['edges']}
    physical, owner = _inventory(cells, scoped_nets)
    root = component['root']
    if component.get('canonical') != root or cells[_cell(root)].get('ref') not in {'FDRE', 'FDSE'}:
        raise ValueError('invalid_canonical_root')
    if not _editable(cells[_cell(root)]):
        raise ValueError('protected_root')
    if replica_name in cells:
        raise ValueError('replica_already_exists:' + replica_name)
    replica_key = replica_name + '/Q'
    wanted = set(component.get('terminals', {}).get(target_slr, []))
    if not wanted:
        raise ValueError('empty_target_group')
    for key, sinks in component['edges'].items():
        if physical.get(key, []) != sinks:
            raise ValueError('stale_component_boundary:' + key)
    transparent = set(component['transparent'])
    barriers = component['barriers']
    summary = {}
    active = set()

    def descendants(driver):
        if driver in summary:
            return summary[driver]
        if driver in active:
            raise ValueError('identity_cycle:' + driver)
        active.add(driver)
        leaves = set()
        clean = True
        local = True
        cap_ok = len(physical.get(driver, [])) <= branch_limit
        for sink in physical.get(driver, []):
            c = _cell(sink)
            if sink in barriers:
                clean = False
            elif c in transparent and _pin(sink) == 'I0':
                if not _editable(cells[c]) or not _identity(cells[c]):
                    raise ValueError('stale_identity:' + c)
                child, child_clean, child_local, child_cap = descendants(c + '/O')
                leaves |= child
                clean &= child_clean
                local &= child_local and cells[c]['slr'] == target_slr
                cap_ok &= child_cap
            else:
                if (not _editable(cells[c]) or not _ordinary(cells[c], _pin(sink))):
                    raise ValueError('stale_terminal:' + sink)
                leaves.add(sink)
                local &= cells[c]['slr'] == target_slr
        active.remove(driver)
        summary[driver] = (leaves, clean, local, cap_ok)
        return summary[driver]

    descendants(root)
    reused = []
    covered = set()
    attachments = []

    def choose(driver):
        for sink in physical.get(driver, []):
            c = _cell(sink)
            if sink in barriers:
                continue
            if c in transparent and _pin(sink) == 'I0':
                leaves, clean, local, cap_ok = summary[c + '/O']
                if (leaves and leaves <= wanted and clean and local and cap_ok
                        and cells[c]['slr'] == target_slr):
                    x, y = _position(cells, sink)
                    attachments.append(dict(pin=sink, x=x, y=y))
                    reused.append(c)
                    covered.update(leaves)
                else:
                    choose(c + '/O')
            elif sink in wanted:
                x, y = _position(cells, sink)
                attachments.append(dict(pin=sink, x=x, y=y))
                covered.add(sink)

    choose(root)
    if covered != wanted:
        raise ValueError('terminal_coverage_mismatch')
    if len({i['pin'] for i in attachments}) != len(attachments):
        raise ValueError('duplicate_cut_owner')
    clones = {}
    rewires = {}
    new_links = {}
    hints = {}
    template = next(iter(sorted(transparent)), None)
    if template is None and len(attachments) > branch_limit:
        # Caller may supply a real global identity template for native snapshots.
        template = next((n for n, c in sorted(cells.items()) if _identity(c) and _editable(c)), None)
    serial = 0

    def connect(source, pin):
        if pin in owner:
            if owner[pin] != source:
                rewires[pin] = source
        elif _cell(pin) in clones and _pin(pin) == 'I0':
            new_links[pin] = source
            clones[_cell(pin)]['inputs']['I0'] = source
        else:
            raise ValueError('unknown_attachment:' + pin)

    current = sorted(attachments, key=lambda i: i['pin'])
    levels = 0
    while len(current) > branch_limit:
        next_level = []
        for group in _clusters(current, branch_limit):
            serial += 1
            token = repr((root, target_slr, replica_name, serial)).encode()
            name = 'sbeco_bcast_' + hashlib.sha256(token).hexdigest()[:20]
            if name in cells or name in clones:
                raise ValueError('clone_name_collision:' + name)
            x = sum(i['x'] for i in group) / len(group)
            y = sum(i['y'] for i in group) / len(group)
            clones[name] = dict(ref='LUT1', config={'INIT': "2'h2"}, slr=target_slr,
                                x=x, y=y, origin=template, inputs={})
            hints[name] = dict(slr=target_slr, x=x, y=y)
            for item in group:
                connect(name + '/O', item['pin'])
            next_level.append(dict(pin=name + '/I0', x=x, y=y))
        current = next_level
        levels += 1
    for item in current:
        connect(replica_key, item['pin'])
    changed = {owner[pin] for pin in rewires}
    expected = {key: set(physical[key]) for key in changed}
    expected[replica_key] = set()
    expected.update({name + '/O': set() for name in clones})
    for pin, source in rewires.items():
        expected[owner[pin]].remove(pin)
        expected[source].add(pin)
    for pin, source in new_links.items():
        expected[source].add(pin)
    for key, sinks in expected.items():
        if key not in physical and len(sinks) > branch_limit:
            raise ValueError('new_output_over_cap:' + key)
        if key in physical and len(sinks) > len(physical[key]):
            raise ValueError('original_output_fanout_increased:' + key)
    # Capture every retained subtree node for target-SLR placement verification.
    reused_nodes = set()
    def retained(c):
        if c in reused_nodes:
            return
        reused_nodes.add(c)
        for sink in physical.get(c + '/O', []):
            if _cell(sink) in transparent and _pin(sink) == 'I0':
                retained(_cell(sink))
    for c in reused:
        retained(c)
    return dict(clones=clones, rewires=dict(sorted(rewires.items())),
                expected={k: sorted(v) for k, v in sorted(expected.items())},
                metadata=dict(canonical=root, target_slr=target_slr,
                              owner=root + '@' + target_slr, replica=replica_name,
                              terminals=sorted(wanted), cut_pins=sorted(i['pin'] for i in attachments),
                              original_drivers={p: owner[p] for p in sorted(rewires)},
                              reused_subtrees=sorted(reused), reused_nodes=sorted(reused_nodes),
                              retained_original_cells=True, added_lut_levels=levels,
                              branch_limit=branch_limit, hints=hints,
                              removed_original_cells=[]))
