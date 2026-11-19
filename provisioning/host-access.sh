#!/usr/bin/env bash
set -euo pipefail
[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || { echo 'LFCS provisioning: candidate guest marker missing' >&2; exit 1; }

# Lima's SSH connection is the lab control plane. Curriculum SSH exercises use
# isolated configs under /etc/lfcs-lab, so always retain a listener on port 22
# without changing those exercise-owned configurations.
active=/etc/ssh/sshd_config
baseline=/etc/lfcs-lab/host-sshd_config.baseline
dropin=/etc/ssh/sshd_config.d/00-lfcs-management.conf
package_baseline=/var/lib/ucf/cache/:etc:ssh:sshd_config

ensure_hostname_mapping() {
  local static_hostname
  static_hostname=$(hostnamectl --static 2>/dev/null || hostname)
  [[ -n $static_hostname ]] || return 0
  if ! awk -v wanted="$static_hostname" '
    $1 !~ /^#/ { for (i=2; i<=NF; i++) if ($i == wanted) found=1 }
    END { exit !found }
  ' /etc/hosts; then
    printf '127.0.1.1\t%s\n' "$static_hostname" >>/etc/hosts
  fi
}

ensure_hostname_mapping
[[ ${1:-} == --hostname-only ]] && exit 0

install -d -o root -g root -m 0755 /etc/lfcs-lab /etc/ssh/sshd_config.d /run/sshd

if [[ ! -s $baseline ]]; then
  if [[ -s $package_baseline ]]; then
    install -o root -g root -m 0644 "$package_baseline" "$baseline"
  elif /usr/sbin/sshd -t; then
    install -o root -g root -m 0644 "$active" "$baseline"
  else
    echo "Cannot establish a valid host SSH baseline" >&2
    exit 1
  fi
fi

if ! cmp -s "$baseline" "$active"; then
  install -o root -g root -m 0644 "$baseline" "$active"
fi

printf '%s\n' \
  '# LFCS infrastructure control-plane listener; scenarios use isolated configs.' \
  'Port 22' >"$dropin"
chmod 0644 "$dropin"

if ! /usr/sbin/sshd -t; then
  install -o root -g root -m 0644 "$baseline" "$active"
  /usr/sbin/sshd -t
fi

systemctl unmask ssh.service ssh.socket >/dev/null 2>&1 || true
systemctl enable ssh.service >/dev/null 2>&1
if [[ ${1:-} == --boot ]]; then
  # cloud-init's bootcmd runs before the normal service graph has settled;
  # waiting for a restart here can deadlock early boot and prevent SSH itself.
  systemctl --no-block restart ssh.service
else
  systemctl restart ssh.service
fi
