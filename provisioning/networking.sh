#!/usr/bin/env bash
set -euo pipefail
[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || { echo 'LFCS provisioning: candidate guest marker missing' >&2; exit 1; }
/usr/local/lib/lfcs/topology.sh reset
