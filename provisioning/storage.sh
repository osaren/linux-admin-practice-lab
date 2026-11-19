#!/usr/bin/env bash
set -euo pipefail
[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || { echo 'LFCS provisioning: candidate guest marker missing' >&2; exit 1; }
mkdir -p /var/lib/lfcs-disks /mnt/lfcs/{data,xfs,lvm,swap,nfs,sshfs,auto}
chmod 0700 /var/lib/lfcs-disks
/usr/local/lib/lfcs/storage.sh reset-all
