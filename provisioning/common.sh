#!/usr/bin/env bash
set -euo pipefail
[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || { echo 'LFCS provisioning: candidate guest marker missing' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
mkdir -p /var/lib/lfcs-lab /var/lib/lfcs-disks /etc/lfcs-lab /srv/lfcs
hostnamectl set-hostname lfcs

apt-get update
apt-get install -y --no-install-recommends \
  acl at attr auditd autofs busybox-static bzip2 curl dnsutils e2fsprogs file findutils \
  fuse3 gawk git grep gzip iproute2 iptables iputils-ping jq less lsof lvm2 \
  netcat-openbsd netplan.io network-manager nbd-client nbd-server nfs-common \
  nfs-kernel-server nftables nginx openssh-client openssh-server openssl parted \
  procps psmisc python3-yaml rsync sed sshfs sudo tar tcpdump traceroute tree \
  util-linux vim wget xfsprogs xz-utils

if ! id student >/dev/null 2>&1; then
  useradd -m -s /bin/bash student
fi
install -d -o student -g student -m 0700 /home/student/.ssh
/usr/local/lib/lfcs/ssh-ownership.py ensure-baseline
printf 'student ALL=(ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/00-lfcs-student-admin
chmod 0440 /etc/sudoers.d/00-lfcs-student-admin
rm -f /etc/sudoers.d/90-lfcs-student
passwd -d student >/dev/null 2>&1 || true

systemctl enable --now ssh atd >/dev/null 2>&1 || true
/usr/local/lib/lfcs/ensure-host-access.sh
systemctl disable --now autofs nginx nftables nfs-server nbd-server >/dev/null 2>&1 || true
# SysV-generated units can be disabled without --now stopping their active state.
systemctl stop autofs nginx nftables nfs-server nbd-server >/dev/null 2>&1 || true
/usr/local/lib/lfcs/nginx-ownership.py reset-all
systemctl enable --now NetworkManager >/dev/null 2>&1 || true
if ! grep -Eq '^[[:space:]]*allowlist[[:space:]]*=' /etc/nbd-server/config; then
  sed -i '/^\[generic\]$/a\    allowlist = true' /etc/nbd-server/config
fi

cat >/etc/motd <<'EOF'
LFCS disposable practice VM. Work as student; use sudo where required.
Simulated hosts: ./bin/lfcs shell node1|node2|node3|router1
EOF

apt-get clean
rm -rf /var/lib/apt/lists/*
journalctl --vacuum-size=32M >/dev/null 2>&1 || true
touch /var/lib/lfcs-lab/provisioned-v1
