#!/usr/bin/env bash
set -eo pipefail
cd "$RUN_DIR"
printf 'QUEUED %s\n' "$(date -Is)" > phase.txt
exec 9>"$BATCH_DIR/orb_compile.lock"
flock 9
while [ "$(awk '/MemAvailable:/ {print int($2/1024/1024)}' /proc/meminfo)" -lt 32 ]; do
  printf 'WAIT_MEMORY %s\n' "$(date -Is)" > phase.txt
  sleep 60
done
printf 'STARTING %s\n' "$(date -Is)" > phase.txt
bash inputs/run.sh
