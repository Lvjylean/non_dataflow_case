"""Emit a bounded candidate view from the authoritative prepare graph.

The existing complete graph is borrowed, never copied. This file only adds
targeted records to Tcl. Native clock validation and native configuration/STA
remain in the current read epoch; unsupported evidence causes native fallback.
"""
import collections
import csv
import json
from pathlib import Path
import re
import time

import joint_input as joint

SCHEMA = 'targeted-native-input-v1'
MAX_CELLS = 65536
MAX_LOADS = 262144
# A bounded 128 MiB candidate view avoids truncating normal GETRF input cones.
# Cell/load budgets remain unchanged; this is never the complete design graph.
MAX_BYTES = 128 * 1024 * 1024
COMB = re.compile(r'^(LUT[1-6]|MUXF[789])$')


def table(path):
    with Path(path).open() as stream:
        yield from csv.DictReader(stream, delimiter='\t')


def required_pins(ref):
    if re.fullmatch(r'LUT[1-6]', ref):
        return {f'I{i}' for i in range(int(ref[-1]))}
    if ref in {'MUXF7', 'MUXF8', 'MUXF9'}:
        return {'I0', 'I1', 'S'}
    if ref in {'FDRE', 'FDSE'}:
        return {'C', 'D', 'CE', 'R' if ref == 'FDRE' else 'S'}
    return None


def emit_prepared(folder, cells, nets, requests, templates):
    """Reuse only complete pin sets and independently counted native nets.

    Seed templates also include complete selected MUX macros and control
    aliases. Upstream expansion is a superset of the bounded native D traversal;
    anything outside this bounded view simply executes the reference reads.
    """
    folder = Path(folder)
    started = time.perf_counter()
    stats = collections.Counter()
    result = dict(schema=SCHEMA, epoch='', cells={}, nets={})
    try:
        metadata = {r['key']: r['value'] for r in table(folder/'metadata.tsv')}
        if (metadata.get('status') != 'PASS' or metadata.get('reuse_schema') != SCHEMA
                or not metadata.get('reuse_epoch')):
            raise ValueError('missing_current_capture_epoch')
        result['epoch'] = metadata['reuse_epoch']
        selected = set()
        pending = collections.deque((name, 0) for name in sorted(set(templates)))
        for request in requests:
            name = request['key'].rsplit('/', 1)[0]
            pending.append((name, 0))
            # A template need not itself be a copied FF, but all D-cone
            # branches of each requested FF must be available for traversal.
            key = cells.get(name, {}).get('inputs', {}).get('D', '')
            if '/' in key and not key.startswith(('barrier ', 'constant ', 'clock ')):
                pending.append((key.rsplit('/', 1)[0], 0))
        while pending and len(selected) < MAX_CELLS:
            name, depth = pending.popleft()
            if name in selected or name not in cells:
                continue
            selected.add(name)
            cell = cells[name]
            if COMB.fullmatch(cell['ref']) and depth <= 16:
                for key in cell.get('inputs', {}).values():
                    if '/' in key and not key.startswith(('barrier ', 'constant ', 'clock ')):
                        pending.append((key.rsplit('/', 1)[0], depth+1))
        stats['cell_budget_fallback'] = int(bool(pending))
        stats['selected_cells'] = len(selected)
        needed = set()
        for name in sorted(selected):
            cell = cells[name]
            expected = required_pins(cell['ref'])
            if expected is None:
                stats['unsupported_cell_fallback'] += 1
                continue
            inputs = dict(cell.get('inputs', {}))
            if cell['ref'] in {'FDRE', 'FDSE'}:
                # Capturing every global-clock C pin would inflate the native
                # batch by hundreds of thousands of pins. Keep C entirely
                # native; ji::record still enumerates every real input and
                # uses these descriptors only for individual D/CE/R/S reads.
                expected = expected-{'C'}
                inputs.pop('C', None)
            if set(inputs) != expected or any(k.startswith('barrier ') for k in inputs.values()):
                stats['incomplete_cell_fallback'] += 1
                continue
            if any(k.startswith('clock ') for p, k in inputs.items() if p != 'C'):
                stats['clock_as_data_fallback'] += 1
                continue
            descriptors = {}
            for pin, key in inputs.items():
                if key.startswith('constant '):
                    # Vivado's subprocess PATH may select Python 3.8.
                    kind, value = 'constant', key[len('constant '):]
                else:
                    kind, value = 'ordinary', key
                descriptors[pin] = dict(kind=kind, value=value)
            result['cells'][name] = descriptors
            for key in inputs.values():
                if not key.startswith(('constant ', 'clock ')):
                    needed.add(key)
            needed.add(name+('/Q' if cell['ref'] in {'FDRE', 'FDSE'} else '/O'))
        # Outputs needed only for receiver positions may belong to a source
        # outside the template set; input net keys above cover those too.
        seen = set()
        loads = 0
        for row in table(folder/'reuse_nets.tsv'):
            key = row['key']
            if key not in needed:
                continue
            if key in seen:
                result['nets'].pop(key, None)
                stats['ambiguous_net_fallback'] += 1
                continue
            seen.add(key)
            before = nets.get(key, ())
            try:
                safe = row['safe'] == '1' and int(row['sinks']) == len(before)
            except (KeyError, ValueError):
                safe = False
            if not safe or len(before) != len(set(before)) or any(p.startswith('barrier ') for p in before):
                stats['unsafe_net_fallback'] += 1
                continue
            if loads+len(before) > MAX_LOADS:
                stats['load_budget_fallback'] += 1
                continue
            # sorted() gives the exact reference sb::loads canonical order.
            result['nets'][key] = dict(root=row['root'], before=sorted(before))
            loads += len(before)
        stats['retained_loads'] = loads
        stats['retained_cells'] = len(result['cells'])
        stats['retained_nets'] = len(result['nets'])
    except (OSError, KeyError, ValueError) as error:
        # A missing slim sidecar never changes planning admission. The Tcl
        # reader sees an empty view and executes every original native query.
        result['cells'] = {}; result['nets'] = {}
        stats['snapshot_unavailable'] += 1
        stats['reason'] = str(error)
    target = folder/'input_snapshot.tcl'
    temporary = target.with_suffix('.tcl.tmp')
    def base():
        empty = dict(schema=SCHEMA, epoch=result['epoch'], cells={}, nets={})
        return 'set locality_reuse_snapshot '+joint.word(joint.tcl(empty))+'\n'
    size = 0
    written = collections.Counter()
    emitted_nets = set()
    def records():
        # Interleave each cell with its needed signals. A byte-capped prefix
        # then contains useful complete cells instead of only an input index.
        for key, value in result['cells'].items():
            yield 'cells', key, value
            ref = cells[key]['ref']
            keys = [d['value'] for d in value.values() if d['kind'] == 'ordinary']
            keys.append(key+('/Q' if ref in {'FDRE', 'FDSE'} else '/O'))
            for net in keys:
                if net in result['nets'] and net not in emitted_nets:
                    emitted_nets.add(net)
                    yield 'nets', net, result['nets'][net]
    with temporary.open('w') as stream:
        line = base(); stream.write(line); size += len(line.encode())
        for category, key, value in records():
            line = ('dict set locality_reuse_snapshot '+category+' '+joint.word(key)
                    +' '+joint.word(joint.tcl(value))+'\n')
            line_bytes = len(line.encode())
            if size+line_bytes > MAX_BYTES:
                stats['byte_budget_fallback'] += 1
                break
            stream.write(line);size += line_bytes;written[category] += 1
    temporary.replace(target)
    stats['serialized_cell_records'] = written['cells']
    stats['serialized_net_records'] = written['nets']
    stats['serialized_bytes'] = target.stat().st_size
    stats['elapsed_seconds'] = time.perf_counter()-started
    stats['proof_schema'] = SCHEMA
    stats['proof_epoch'] = result['epoch']
    stats['proof_source'] = 'complete_prepare_graph_and_native_capture_sidecars'
    (folder/'input_snapshot_prepare.json').write_text(json.dumps(dict(stats), indent=2)+'\n')
    return dict(stats)
