#!/usr/bin/env python3
"""Add memory waits only; forward all native arguments without changing the flow."""
import json
import os
from pathlib import Path
import sys


def adapt(args, config, here):
    args = list(args)
    if args.count('-source') != 1:
        raise ValueError('Exactly one native source is required')
    index = args.index('-source')+1
    script = Path(args[index]).resolve()
    flow = Path(config['second_root'])/'flow'
    if script not in (flow/'chain.tcl', flow/'code/regional/run.tcl'):
        raise ValueError('Unexpected native source')
    args[index] = str(here/'entry.tcl')
    return args, dict(PHASE_NATIVE_SCRIPT=str(script), PHASE_FLOW_ROOT=str(flow),
                      PHASE_GATE_TOOL=str(here/'gate.py'), PHASE_GATE_DIR=config['gate_directory'])


def main():
    here = Path(__file__).resolve().parent
    config = json.loads((here/'config.json').read_text())
    args, extra = adapt(sys.argv[1:], config, here)
    os.environ.update(extra)
    os.execv(config['vivado'], [config['vivado'], *args])


if __name__ == '__main__':
    main()
