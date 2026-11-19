#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
bash -n "$ROOT/lib/topology.sh"
bash -n "$ROOT/lib/storage.sh"
bash -n "$ROOT/lib/scenario-engine.sh"
python3 -m py_compile "$ROOT/lib/special-engine.py"
for f in "$ROOT"/provisioning/*.sh "$ROOT"/bin/*; do
  case "$f" in *.py) continue;; esac
  bash -n "$f"
done
for f in "$ROOT"/tests/special-*.sh "$ROOT"/completions/lfcs.bash; do bash -n "$f"; done
if [[ ${1:-} == --skip-zsh ]]; then
  echo 'Zsh syntax delegated to the macOS CI jobs.'
else
  zsh -n "$ROOT/completions/_lfcs"
fi
python3 -Werror -m py_compile "$ROOT/lib/catalog.py" "$ROOT/lib/extended_catalog.py" "$ROOT/lib/special_catalog.py" "$ROOT/lib/lfcs.py" "$ROOT/lib/extended-engine.py" "$ROOT/lib/nginx-ownership.py" "$ROOT/lib/systemd-ownership.py" "$ROOT/lib/ssh-ownership.py" "$ROOT/lib/solutions.py"
python3 - <<'PY'
import pathlib
import re
import sys
sys.path.insert(0, 'lib')
from collections import Counter
from catalog import LABS, BY_ID, MOCKS, MINIS
assert len(LABS) >= 150, len(LABS)
assert len(BY_ID) == len(LABS)
counts=Counter(x['domain'] for x in LABS)
assert counts['operations'] >= 30, counts
assert counts['networking'] >= 35, counts
assert counts['storage'] >= 25, counts
assert counts['commands'] >= 30, counts
assert counts['users'] >= 18, counts
assert len(MINIS) >= 5 and all(6 <= len(v) <= 8 for v in MINIS.values())
assert all(len(v) in range(17,21) for v in MOCKS.values())
assert all(i in BY_ID for v in MOCKS.values() for i in v)
assert all(i in BY_ID for v in MINIS.values() for i in v)
assert set(MOCKS) == {str(n) for n in range(1, 7)}

# The QA solver and the independently implemented validator must cover the
# whole real catalogue.  Missing case arms otherwise remain invisible until a
# long live regression reaches them.
root = pathlib.Path('.')
ids = set(BY_ID)
case_label = re.compile(r'^\s{2}([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)*)\)')
coverage_groups = (
    ('QA solver', ('tests/guest-regression-solutions.sh',
                   'tests/guest-full-regression-solutions.sh',
                   'tests/special-scenario-solutions.sh')),
    ('independent validator', ('tests/guest-independent-validations.sh',
                               'tests/special-independent-validations.sh')),
)
for label, relatives in coverage_groups:
    covered = set()
    for relative in relatives:
        for line in (root / relative).read_text().splitlines():
            match = case_label.match(line)
            if match:
                covered.update(match.group(1).split('|'))
    missing = sorted(ids - covered)
    assert not missing, f'{label} lacks catalogue cases: {missing}'

# nbd-01 promises infrastructure supplied by staging.  Keep the task,
# staging implementation, grader, and reset ownership aligned.
nbd_task = ' '.join(BY_ID['nbd-01']['requirements'])
assert '/mnt/lfcs/amber/sentinel' in nbd_task
engine = (root / 'lib/extended-engine.py').read_text()
storage = (root / 'lib/storage.sh').read_text()
provision = (root / 'provisioning/common.sh').read_text()
for token in ('/etc/nbd-server/conf.d/amber.conf', '[amber]',
              '/var/lib/lfcs-disks/amber.img'):
    assert token in engine, f'nbd-01 engine contract lacks {token}'
assert '/usr/local/lib/lfcs/nbd-ownership.py teardown' in storage
assert 'lib/nbd-ownership.py' in (root / 'lib/lfcs.py').read_text()
assert 'allowlist = true' in provision

# Public scenario entry points must synchronize newly added guest helpers into
# existing VMs before invoking engines that depend on them.
lfcs = (root / 'lib/lfcs.py').read_text()
assert 'lib/nginx-ownership.py' in lfcs
assert 'lib/systemd-ownership.py' in lfcs
assert 'lib/ssh-ownership.py' in lfcs
assert 'lib/special-engine.py' in lfcs
assert 'lfcs-special' in lfcs
assert 'provisioning/host-access.sh' in lfcs
assert lfcs.count('sync_runtime_scripts()') >= 3

# Generic storage reset must not own the learner's active autofs paths.  Only
# the explicitly autofs-specific reset branches may remove those resources.
mount_array = storage.split('MOUNTS=(', 1)[1].split(')', 1)[0]
assert '/mnt/lfcs/auto' not in mount_array
assert '/mnt/lfcs/on-demand' not in mount_array
special_ids = {x['id'] for x in LABS if x['host'] == 'lfcs-special'}
assert special_ids == ({f'selinux-{n:02d}' for n in range(1, 7)} |
                       {f'ldap-{n:02d}' for n in range(1, 6)})
assert all(x['host'] in {'lfcs', 'lfcs-special', 'node1', 'node2', 'node3', 'router1'} for x in LABS)
print(f"catalog: {len(LABS)} labs; counts={dict(counts)}; minis={len(MINIS)}; mocks={len(MOCKS)}")
PY
echo "static checks passed"
