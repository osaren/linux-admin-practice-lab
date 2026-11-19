#!/usr/bin/env bash
set -euo pipefail
[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || { echo 'LFCS provisioning: candidate guest marker missing' >&2; exit 1; }
mkdir -p /srv/lfcs/{node1,node2,node3,share} /var/log/lfcs-lab
printf 'backend=node2\n' >/srv/lfcs/node2/index.html
printf 'backend=node3\n' >/srv/lfcs/node3/index.html
chown -R student:student /srv/lfcs
cat >/etc/systemd/system/lfcs-sleeper.service <<'EOF'
[Unit]
Description=LFCS practice sleeper
[Service]
ExecStart=/usr/bin/sleep infinity
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
