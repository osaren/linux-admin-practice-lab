#!/usr/bin/env bash
set -euo pipefail
[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || { echo 'LFCS provisioning: candidate guest marker missing' >&2; exit 1; }

install -d /etc/NetworkManager/conf.d
printf '[keyfile]\nunmanaged-devices=none\n' >/etc/NetworkManager/conf.d/90-lfcs-managed.conf
systemctl restart NetworkManager
export DEBIAN_FRONTEND=noninteractive

install -d /var/lib/lfcs-lab/backups /etc/systemd/timesyncd.conf.d

# Keep the former Chrony policy available for inspection even though timesyncd is
# the selected implementation for this Ubuntu-focused lab.
if [[ -d /etc/chrony && ! -e /var/lib/lfcs-lab/backups/chrony ]]; then
  cp -a /etc/chrony /var/lib/lfcs-lab/backups/chrony
fi

printf '%s\n' \
  'iptables-persistent iptables-persistent/autosave_v4 boolean false' \
  'iptables-persistent iptables-persistent/autosave_v6 boolean false' |
  debconf-set-selections

apt-get update
apt-get install -y --no-install-recommends \
  anacron build-essential cron docker.io iptables-persistent libvirt-clients man-db \
  manpages manpages-dev netfilter-persistent policycoreutils qemu-utils \
  selinux-utils sysstat systemd-timesyncd virtinst

cat >/etc/systemd/timesyncd.conf.d/90-lfcs.conf <<'EOF'
[Time]
NTP=time.cloudflare.com
FallbackNTP=ntp.ubuntu.com
EOF

systemctl disable --now chrony.service >/dev/null 2>&1 || true
systemctl enable --now systemd-timesyncd.service docker.service >/dev/null
usermod -aG docker student
nginx_image='nginx@sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11'
docker image inspect "$nginx_image" >/dev/null 2>&1 || docker pull "$nginx_image"
docker tag "$nginx_image" nginx:alpine

# Lima's host account owns a very large subordinate-ID range. Keep existing
# mappings (including student's Podman mapping) but avoid allocating a new range
# to every disposable scenario user.
sed -i -E 's/^SUB_UID_COUNT[[:space:]]+.*/SUB_UID_COUNT 0/; s/^SUB_GID_COUNT[[:space:]]+.*/SUB_GID_COUNT 0/' /etc/login.defs

# Keep the persistent-rules service installed but inactive until a scenario asks
# for it; loading arbitrary saved rules on normal boot would be surprising.
systemctl disable netfilter-persistent.service >/dev/null 2>&1 || true

apt-get clean
rm -rf /var/lib/apt/lists/*
journalctl --vacuum-size=32M >/dev/null 2>&1 || true
touch /var/lib/lfcs-lab/provisioned-v2
