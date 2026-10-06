"""Wait outside a native phase until the single scheduler grants its memory lease."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid
from policy import BUDGETS, lease_valid, read_json, write


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--directory', type=Path, required=True)
    ap.add_argument('--stage', choices=list(BUDGETS), required=True)
    args = ap.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    request = dict(nonce=uuid.uuid4().hex, stage=args.stage, requested_gib=BUDGETS[args.stage],
                   time=time.time(), gate_pid=os.getpid(), native_pid=os.getppid())
    write(args.directory/'request.json', request)
    waited = time.monotonic()
    while True:
        grant = read_json(args.directory/'grant.json')
        if lease_valid(grant, request, time.time()):
            receipt = dict(request, granted_at=time.time(), wait_seconds=time.monotonic()-waited,
                           admission=grant['admission'])
            write(args.directory/'receipt.json', receipt)
            write(args.directory/('receipt_'+request['nonce']+'.json'), receipt)
            print(json.dumps(receipt), flush=True)
            return
        write(args.directory/'waiting.json', dict(request, wait_seconds=time.monotonic()-waited))
        time.sleep(2)


if __name__ == '__main__':
    main()
