#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
for spec in 'storage.sh reset-all' 'topology.sh destroy' 'scenario-engine.sh reset operations-01'; do
  read -r -a args <<<"$spec"
  if bash "$ROOT/lib/${args[0]}" "${args[@]:1}" >"$ROOT/tmp/privileged-guard.out" 2>&1; then
    echo "FAIL: ${args[0]} ran outside candidate guest" >&2; exit 1
  fi
  grep -q 'candidate guest marker missing' "$ROOT/tmp/privileged-guard.out" || {
    echo "FAIL: ${args[0]} did not fail at guest marker" >&2; exit 1;
  }
done
for spec in 'extended-engine.py reset operations-01' 'special-engine.py reset selinux-01' 'nbd-ownership.py teardown' 'ssh-ownership.py reset-all' 'nginx-ownership.py reset-all' 'systemd-ownership.py reset operations-01'; do
  read -r -a args <<<"$spec"
  if python3 "$ROOT/lib/${args[0]}" "${args[@]:1}" >"$ROOT/tmp/privileged-guard.out" 2>&1; then
    echo "FAIL: ${args[0]} ran outside candidate guest" >&2; exit 1
  fi
  grep -q 'candidate guest marker missing' "$ROOT/tmp/privileged-guard.out" || {
    echo "FAIL: ${args[0]} did not fail at guest marker" >&2; exit 1;
  }
done
for file in "$ROOT"/provisioning/*.sh; do
  if bash "$file" >"$ROOT/tmp/privileged-guard.out" 2>&1; then
    echo "FAIL: ${file##*/} ran outside candidate guest" >&2; exit 1
  fi
  grep -q 'candidate guest marker missing' "$ROOT/tmp/privileged-guard.out" || {
    echo "FAIL: ${file##*/} did not fail at guest marker" >&2; exit 1;
  }
done
rm -f "$ROOT/tmp/privileged-guard.out"
echo 'PASS: all 16 privileged entry points refuse execution outside candidate guest'
