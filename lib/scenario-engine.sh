#!/usr/bin/env bash
set -uo pipefail
MODE=${1:-}
ID=${2:-}
[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || { echo 'LFCS scenario engine: candidate guest marker missing' >&2; exit 1; }
[[ $ID =~ ^[a-z0-9-]+$ ]] || { echo 'LFCS scenario engine: invalid scenario ID' >&2; exit 2; }
STATE=/var/lib/lfcs-lab
RUN=/run/lfcs-lab
mkdir -p "$STATE" "$RUN" /srv/lfcs /mnt/lfcs

pass() { printf 'PASS|%s\n' "$*"; }
fail() { printf 'FAIL|%s\n' "$*"; }
check() { local msg=$1; shift; if "$@" >/dev/null 2>&1; then pass "$msg"; else fail "$msg"; fi; }
has_line() { grep -Eq "$2" "$1" 2>/dev/null; }
fstab_uuid_entry() {
  local device=$1 target=$2 fstype=$3 required=${4:-} uuid source found_target found_type options option
  uuid=$(blkid -s UUID -o value "$device" 2>/dev/null) || return 1
  while read -r source found_target found_type options; do
    source=${source//\"/}
    found_target=${found_target//\"/}
    [[ $source == "UUID=$uuid" && $found_target == "$target" && $found_type == "$fstype" ]] || continue
    for option in ${required//,/ }; do
      [[ ,$options, == *,$option,* ]] || continue 2
    done
    return 0
  done < <(findmnt --fstab --raw -rn -o SOURCE,TARGET,FSTYPE,OPTIONS)
  return 1
}
export -f fstab_uuid_entry
nfs_export_restricted() {
  local export_path=$1 allowed_network=$2
  NFS_EXPORT_PATH="$export_path" NFS_ALLOWED_NETWORK="$allowed_network" exportfs -s 2>/dev/null |
    NFS_EXPORT_PATH="$export_path" NFS_ALLOWED_NETWORK="$allowed_network" python3 -c '
import ipaddress, os, sys
path=os.environ["NFS_EXPORT_PATH"]
allowed=ipaddress.ip_network(os.environ["NFS_ALLOWED_NETWORK"])
found=False
for raw in sys.stdin:
    fields=raw.split()
    if not fields or fields[0] != path:
        continue
    found=True
    for spec in fields[1:]:
        client=spec.split("(",1)[0]
        options=spec.split("(",1)[1].rstrip(")").split(",") if "(" in spec else []
        try:
            network=ipaddress.ip_network(client if "/" in client else client+"/32", strict=False)
        except ValueError:
            raise SystemExit(1)
        if not network.subnet_of(allowed) or "rw" not in options:
            raise SystemExit(1)
raise SystemExit(0 if found else 1)
'
}
export -f nfs_export_restricted
tls_material_check() {
  local dir=$1 criterion=$2 identity=${3:-} seconds=${4:-0}
  local file key cert key_hash cert_hash subject
  local -a keys=() certs=()
  [[ -d $dir ]] || return 1
  while IFS= read -r -d '' file; do
    openssl pkey -in "$file" -noout </dev/null >/dev/null 2>&1 && keys+=("$file")
    openssl x509 -in "$file" -noout >/dev/null 2>&1 && certs+=("$file")
  done < <(find "$dir" -maxdepth 1 -type f -print0 | sort -z)
  case "$criterion" in
    key) ((${#keys[@]} > 0)); return ;;
    key_mode)
      for key in "${keys[@]}"; do [[ $(stat -c %a "$key" 2>/dev/null) == 600 ]] && return 0; done
      return 1 ;;
  esac
  for cert in "${certs[@]}"; do
    cert_hash=$(openssl x509 -in "$cert" -pubkey -noout 2>/dev/null |
      openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')
    [[ -n $cert_hash ]] || continue
    for key in "${keys[@]}"; do
      key_hash=$(openssl pkey -in "$key" -pubout -outform DER 2>/dev/null |
        sha256sum | awk '{print $1}')
      [[ -n $key_hash && $key_hash == "$cert_hash" ]] || continue
      case "$criterion" in
        pair) return 0 ;;
        pair_cn)
          subject=$(openssl x509 -in "$cert" -noout -subject -nameopt RFC2253 2>/dev/null)
          subject=${subject#subject=}
          [[ ,$subject, == *,CN="$identity",* ]] && return 0 ;;
        complete_cn)
          [[ $(stat -c %a "$key" 2>/dev/null) == 600 ]] || continue
          subject=$(openssl x509 -in "$cert" -noout -subject -nameopt RFC2253 2>/dev/null)
          subject=${subject#subject=}
          [[ ,$subject, == *,CN="$identity",* ]] || continue
          openssl x509 -in "$cert" -noout -checkend "$seconds" >/dev/null 2>&1 && return 0 ;;
        complete_host)
          [[ $(stat -c %a "$key" 2>/dev/null) == 600 ]] || continue
          openssl verify -CAfile "$cert" -verify_hostname "$identity" "$cert" >/dev/null 2>&1 || continue
          openssl x509 -in "$cert" -noout -checkend "$seconds" >/dev/null 2>&1 && return 0 ;;
      esac
    done
  done
  return 1
}
tls_endpoint_has_identity() {
  local address=$1 server_name=$2 cert rc
  cert=$(mktemp /tmp/lfcs-live-cert.XXXXXX)
  if ! openssl s_client -connect "$address" -servername "$server_name" -showcerts </dev/null 2>/dev/null |
      awk '/-----BEGIN CERTIFICATE-----/{copy=1} copy{print} /-----END CERTIFICATE-----/{exit}' >"$cert"; then
    rm -f "$cert"
    return 1
  fi
  openssl x509 -in "$cert" -noout >/dev/null 2>&1 || { rm -f "$cert"; return 1; }
  openssl verify -CAfile "$cert" -verify_hostname "$server_name" "$cert" >/dev/null 2>&1
  rc=$?
  rm -f "$cert"
  return "$rc"
}
netexec() { ip netns exec "$@"; }
stop_pid() {
  local f=$1 p n
  [[ -f $f ]] || return 0
  p=$(cat "$f" 2>/dev/null)
  if [[ $p =~ ^[0-9]+$ ]]; then
    if kill -0 "$p" 2>/dev/null; then
      tr '\0' '\n' <"/proc/$p/environ" 2>/dev/null | grep -Fqx "LFCS_LAB_PID=${f##*/}" || {
        echo "LFCS reset: PID $p is not an owned ${f##*/} process; preserved" >&2; return 1;
      }
    fi
    kill "$p" 2>/dev/null || true
    for n in {1..20}; do kill -0 "$p" 2>/dev/null || break; sleep 0.05; done
    kill -9 "$p" 2>/dev/null || true
  fi
  rm -f "$f"
}

delete_nm_profiles_for_interfaces() {
  local uuid interface wanted
  while IFS= read -r uuid; do
    [[ -n $uuid ]] || continue
    interface=$(nmcli -g connection.interface-name connection show "$uuid" 2>/dev/null) || continue
    for wanted in "$@"; do
      if [[ $interface == "$wanted" ]]; then
        nmcli connection delete uuid "$uuid" >/dev/null 2>&1 || true
        break
      fi
    done
  done < <(nmcli -g UUID connection show 2>/dev/null)
}

base_network() { /usr/local/lib/lfcs/topology.sh reset >/dev/null; }
base_storage() { /usr/local/lib/lfcs/storage.sh reset-all >/dev/null; }
repair_nginx_baseline_links() {
  local link target name intended
  for link in /etc/nginx/sites-enabled/*; do
    [[ -L $link ]] || continue
    if [[ ! -e $link ]]; then
      target=$(readlink -- "$link" 2>/dev/null || true)
      case "$target" in
        sites-available/*)
          name=${target#sites-available/}
          [[ $name != */* ]] || continue
          intended=/etc/nginx/sites-available/$name
          [[ -f $intended ]] || continue
          ln -sfn "$intended" "$link" ;;
      esac
    fi
    intended=$(readlink -f -- "$link" 2>/dev/null || true)
    [[ -f $intended ]] || continue
    if grep -Eq '^[[:space:]]*listen[[:space:]]+8091([[:space:]]+default_server)?[[:space:]]*;' "$intended" &&
       grep -Eq '^[[:space:]]*return[[:space:]]+"day1-ready"[[:space:]]*;' "$intended"; then
      sed -i -E 's/^([[:space:]]*)return[[:space:]]+"day1-ready"[[:space:]]*;/\1return 200 "day1-ready";/' "$intended"
    fi
  done
}

nginx_owned() {
  /usr/local/lib/lfcs/nginx-ownership.py "$@"
}

systemd_owned() {
  /usr/local/lib/lfcs/systemd-ownership.py "$@"
}

ssh_owned() {
  /usr/local/lib/lfcs/ssh-ownership.py "$@"
}

ensure_nsswitch_baseline() {
  local baseline="$STATE/nsswitch.clean"
  [[ -f $baseline ]] || cp /etc/nsswitch.conf "$baseline"
  sed -i -E \
    -e 's/^[[:space:]]*passwd:.*/passwd:         files/' \
    -e 's/^[[:space:]]*group:.*/group:          files/' \
    -e 's/^[[:space:]]*hosts:.*/hosts:          files dns/' \
    "$baseline"
}

remove_export_path() {
  local export_path=$1 file
  for file in /etc/exports /etc/exports.d/*.exports; do
    [[ -f $file ]] || continue
    sed -i -E "\\#^[[:space:]]*${export_path}([[:space:]]|$)#d" "$file"
  done
}

remove_autofs_entries() {
  local master_path=$1 nfs_path=$2 file map
  local -a owned_maps=()
  for file in /etc/auto.master /etc/auto.master.d/*; do
    [[ -f $file ]] || continue
    if awk -v root="$master_path" '$1 == root {found=1} END {exit !found}' "$file"; then
      master_owned=yes
    else
      master_owned=no
    fi
    while read -r map; do
      [[ $map == /etc/auto.* ]] && owned_maps+=("$map")
    done < <(awk -v root="$master_path" '$1 == root {print $2}' "$file")
    sed -i -E "\\#^[[:space:]]*${master_path}([[:space:]]|$)#d" "$file"
    if [[ $master_owned == yes && $file == /etc/auto.master.d/* ]] &&
       ! grep -Eq '^[[:space:]]*[^#[:space:]]' "$file"; then
      rm -f "$file"
    fi
  done
  for file in /etc/auto.*; do
    [[ -f $file ]] || continue
    sed -i -E "\\#^[^#]*${nfs_path}([[:space:]]|$)#d" "$file"
    if ! grep -Eq '^[[:space:]]*[^#[:space:]]' "$file"; then
      for map in "${owned_maps[@]}"; do
        if [[ $file == "$map" ]]; then rm -f "$file"; break; fi
      done
      case "$file" in
        /etc/auto.share|/etc/auto.lfcs|/etc/auto.lfcs-*) rm -f "$file" ;;
      esac
    fi
  done
}

reset_one() {
  local id=$1
  case "$id" in
    commands-01) rm -rf /srv/lfcs/search /tmp/lfcs-report; userdel -r scout >/dev/null 2>&1 || true ;;
    commands-02) rm -rf /srv/lfcs/config /tmp/lfcs-errors /tmp/lfcs-logs.tar.xz /var/log/lfcs-app.log ;;
    operations-01|operations-02|operations-03) systemd_owned reset "$id" ;;
    operations-04) stop_pid "$RUN/runaway.pid"; stop_pid "$RUN/birch.pid"; stop_pid "$RUN/control.pid" ;;
    operations-05) rm -f /etc/cron.d/lfcs-inventory /usr/local/bin/lfcs-inventory /var/log/lfcs-inventory ;;
    operations-06)
      while read -r job; do
        [[ -n $job ]] || continue
        at -c "$job" 2>/dev/null | grep -Fq '/usr/local/bin/lfcs-once' && atrm "$job"
      done < <(atq 2>/dev/null | awk '{print $1}')
      rm -f /usr/local/bin/lfcs-once ;;
    operations-07) rm -f /etc/sysctl.d/90-lfcs-swappiness.conf; sysctl -q -w vm.swappiness=60 || true ;;
    operations-08) nginx_owned reset "$id" ;;
    networking-*|advanced-0[1-8]) case "$id" in networking-08|networking-09) ssh_owned reset "$id" ;; advanced-01) stop_pid "$RUN/advanced-01-9090.pid"; rm -f "$RUN/advanced-01-9090.log" ;; advanced-05) delete_nm_profiles_for_interfaces br-lfcs br-port1 br-port2 ;; esac; base_network; for n in node1 node2 node3 router1; do netexec "$n" iptables -F >/dev/null 2>&1 || true; netexec "$n" iptables -t nat -F >/dev/null 2>&1 || true; netexec "$n" iptables -P FORWARD ACCEPT >/dev/null 2>&1 || true; done; iptables -D INPUT -j LFCS_HOST >/dev/null 2>&1 || true; iptables -F LFCS_HOST >/dev/null 2>&1 || true; iptables -X LFCS_HOST >/dev/null 2>&1 || true; timesync_changed=no; [[ -e /etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf ]] && timesync_changed=yes; rm -f /etc/netplan/9{0,1}-lfcs-*.yaml /etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf; if [[ $timesync_changed == yes ]]; then systemctl reset-failed systemd-timesyncd >/dev/null 2>&1 || true; systemctl restart systemd-timesyncd >/dev/null 2>&1 || true; fi; nmcli con delete lfcs-dummy >/dev/null 2>&1 || true; ip link del br-lfcs >/dev/null 2>&1 || true; ip link del br-port1 >/dev/null 2>&1 || true; ip link del br-port2 >/dev/null 2>&1 || true; delete_nm_profiles_for_interfaces lfcs-bond0 lfcs-bond-a lfcs-bond-b; ip link del lfcs-bond0 >/dev/null 2>&1 || true; ip link del lfcs-bond-a >/dev/null 2>&1 || true; ip link del lfcs-bond-b >/dev/null 2>&1 || true; case "$id" in advanced-07|advanced-08) nginx_owned reset "$id" ;; esac ;;
    advanced-09) remove_export_path /srv/lfcs/shrae; remove_export_path /srv/lfcs/share; exportfs -ra; systemctl disable --now nfs-server >/dev/null 2>&1 || true ;;
    advanced-10) fusermount3 -u /mnt/lfcs/sshfs >/dev/null 2>&1 || true; umount /mnt/lfcs/sshfs >/dev/null 2>&1 || true; ssh_owned reset "$id"; base_network ;;
    advanced-11)
      systemctl disable --now autofs >/dev/null 2>&1 || true
      for _ in {1..100}; do systemctl is-active --quiet autofs || break; sleep 0.02; done
      systemctl is-active --quiet autofs && return 1
      mountpoint -q /mnt/lfcs/auto/share 2>/dev/null && timeout 5s umount -l /mnt/lfcs/auto/share
      rm -f /etc/auto.master.d/lfcs.autofs /etc/auto.lfcs /etc/exports.d/lfcs.exports
      remove_autofs_entries /mnt/lfcs/auto /srv/lfcs/share
      remove_export_path /srv/lfcs/shrae
      remove_export_path /srv/lfcs/share
      rmdir /etc/exports.d >/dev/null 2>&1 || true
      exportfs -ra
      systemctl disable --now nfs-server >/dev/null 2>&1 || true
      systemctl reset-failed autofs nfs-server >/dev/null 2>&1 || true ;;
    advanced-12)
      /usr/local/lib/lfcs/nbd-ownership.py teardown ;;
    opsusers-01) userdel -r dana >/dev/null 2>&1 || true; groupdel analytics >/dev/null 2>&1 || true; groupdel deploy >/dev/null 2>&1 || true ;;
    opsusers-02) userdel -r contractor >/dev/null 2>&1 || true; groupdel projects >/dev/null 2>&1 || true ;;
    opsusers-03) rm -rf /srv/lfcs/review; groupdel reviewers >/dev/null 2>&1 || true; userdel -r reviewer1 >/dev/null 2>&1 || true ;;
    opsusers-04) rm -f /etc/security/limits.d/90-lfcs.conf ;;
    opsusers-05) rm -f /etc/profile.d/lfcs-region.sh; sed -i '/LFCS_REGION\|TEAM=operations/d' /home/student/.profile 2>/dev/null || true ;;
    opsusers-06|opsusers-07) docker rm -f web-basil web-mint >/dev/null 2>&1 || true; rm -rf /srv/lfcs/container /srv/lfcs/mint /srv/lfcs/wrong-mint ;;
    opsusers-08) rm -f /etc/apt/sources.list.d/lfcs-broken.list /tmp/package-owner ;;
    opsusers-09) rm -f /tmp/selinux-mode /tmp/selinux-fcontext; semanage fcontext -d /srv/selinux-web\(/.*\)\? >/dev/null 2>&1 || true ;;
    opsusers-10) ensure_nsswitch_baseline; cp -f "$STATE/nsswitch.clean" /etc/nsswitch.conf ;;
    opsusers-11) systemd_owned reset "$id" ;;
    opsusers-12) rm -f /tmp/virsh-report /srv/lfcs/domain.xml ;;
    storage-*|day5-readiness) base_storage; rm -rf /srv/lfcs/repo; case "$id" in storage-11|day5-readiness) rm -rf /etc/lfcs/tls ;; storage-12) nginx_owned reset "$id" ;; esac; stop_pid "$RUN/leak.pid"; rm -rf /var/log/lfcs-leak ;;
    day1-mini) reset_one commands-01; reset_one operations-06; systemd_owned reset "$id"; rm -f /etc/sysctl.d/90-lfcs-swappiness.conf /tmp/day1-files "/etc/lfcs-lab/${id}.txt"; sysctl -q -w vm.swappiness=60 || true ;;
    day2-mini) base_network; timesync_changed=no; [[ -e /etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf ]] && timesync_changed=yes; rm -f /etc/netplan/90-lfcs-node1.yaml /etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf "/etc/lfcs-lab/${id}.txt"; sed -i '/api.internal/d' /etc/netns/node1/hosts; if [[ $timesync_changed == yes ]]; then systemctl reset-failed systemd-timesyncd >/dev/null 2>&1 || true; systemctl restart systemd-timesyncd >/dev/null 2>&1 || true; fi ;;
    day4-mini) reset_one opsusers-01; reset_one opsusers-03; reset_one opsusers-11; rm -f /etc/security/limits.d/90-lfcs.conf "/etc/lfcs-lab/${id}.txt" ;;
    *) /usr/local/lib/lfcs/extended-engine.py reset "$id" ;;
  esac
}

setup_sshd() {
  local ns=$1 port=$2 bad=${3:-no} ip
  ip=${ns/node/10.10.}; ip="${ip}.10"
  ssh_owned ensure-baseline
  mkdir -p /srv/lfcs/keys /home/student/.ssh
  cp /srv/lfcs/keys/exam.pub /home/student/.ssh/authorized_keys
  chown student:student /home/student/.ssh /home/student/.ssh/authorized_keys
  chmod 0700 /home/student/.ssh; chmod 0600 /home/student/.ssh/authorized_keys
  cat >"/etc/lfcs-lab/sshd-${ns}.conf" <<EOF
Port $port
ListenAddress $ip
HostKey /etc/ssh/ssh_host_ed25519_key
PidFile $RUN/sshd-${ns}.daemon.pid
AuthorizedKeysFile .ssh/authorized_keys
PubkeyAuthentication yes
PasswordAuthentication no
UsePAM no
StrictModes yes
Subsystem sftp internal-sftp
EOF
  [[ $bad == yes ]] && printf 'InvalidDirective yes\n' >>"/etc/lfcs-lab/sshd-${ns}.conf"
  stop_pid "$RUN/sshd-${ns}.pid"
  if /usr/sbin/sshd -t -f "/etc/lfcs-lab/sshd-${ns}.conf" 2>/dev/null; then
    LFCS_LAB_PID=sshd-${ns}.pid ip netns exec "$ns" /usr/sbin/sshd -D -e -f "/etc/lfcs-lab/sshd-${ns}.conf" >"$RUN/sshd-${ns}.log" 2>&1 &
    echo $! >"$RUN/sshd-${ns}.pid"
    for _ in {1..100}; do
      netexec "$ns" ss -lntH "sport = :$port" 2>/dev/null | grep -q . && return 0
      kill -0 "$(cat "$RUN/sshd-${ns}.pid")" 2>/dev/null || return 1
      sleep 0.02
    done
    return 1
  fi
}

setup_one() {
  local id=$1
  reset_one "$id" || return 1
  case "$id" in operations-08|advanced-07|advanced-08|storage-12) nginx_owned capture "$id" ;; esac
  case "$id" in networking-08|networking-09|advanced-10) ssh_owned capture "$id" ;; esac
  case "$id" in
    commands-01) useradd -m scout; mkdir -p /srv/lfcs/search/{a,b}; truncate -s 12K /srv/lfcs/search/a/alpha; truncate -s 4K /srv/lfcs/search/a/small; truncate -s 16K /srv/lfcs/search/b/beta; chown scout:scout /srv/lfcs/search/{a/alpha,b/beta}; chown root:root /srv/lfcs/search/a/small ;;
    commands-02) mkdir -p /srv/lfcs/config; printf 'mode=exam\n' >/srv/lfcs/config/app.conf; printf 'INFO|start\nERROR|disk\nWARN|slow\nERROR|network\n' >/var/log/lfcs-app.log ;;
    operations-01) printf '#!/bin/sh\necho ready >/run/acorn-api.ready\nexec sleep infinity\n' >/usr/local/bin/acorn-api; chmod 0755 /usr/local/bin/acorn-api; cat >/etc/systemd/system/acorn-api.service <<'EOF'
[Unit]
Description=Acorn API
[Service]
ExecStart=/usr/local/bin/acorn-ap1
Restart=no
[Install]
WantedBy=multi-user.target
EOF
      systemctl daemon-reload; systemctl start acorn-api >/dev/null 2>&1 || true ;;
    operations-02) : ;;
    operations-03) printf '#!/bin/sh\necho v1 >/run/cedar-version; exec sleep infinity\n' >/usr/local/bin/cedar-worker-v1; printf '#!/bin/sh\necho v2 >/run/cedar-version; exec sleep infinity\n' >/usr/local/bin/cedar-worker-v2; chmod 0755 /usr/local/bin/cedar-worker-v{1,2}; cat >/etc/systemd/system/cedar-worker.service <<'EOF'
[Unit]
Description=Cedar worker
[Service]
ExecStart=/usr/local/bin/cedar-worker-v1
[Install]
WantedBy=multi-user.target
EOF
      systemctl daemon-reload; systemctl enable --now cedar-worker >/dev/null ; sed -i 's/v1/v2/' /etc/systemd/system/cedar-worker.service ;;
    operations-04) nohup env LFCS_LAB_PID=runaway.pid LFCS_RUNAWAY=maple sh -c 'while :; do :; done' </dev/null >/dev/null 2>&1 & echo $! >"$RUN/runaway.pid"; nohup env LFCS_LAB_PID=birch.pid sleep 10000 </dev/null >/dev/null 2>&1 & echo $! >"$RUN/birch.pid"; nohup env LFCS_LAB_PID=control.pid sleep 10000 </dev/null >/dev/null 2>&1 & echo $! >"$RUN/control.pid" ;;
    operations-05) printf '#!/bin/sh\ndate -Is > /var/log/lfcs-inventory\n' >/usr/local/bin/lfcs-inventory; chmod 0755 /usr/local/bin/lfcs-inventory; printf '*/5 * * * * lfcs-inventory\n' >/etc/cron.d/lfcs-inventory; chmod 0666 /etc/cron.d/lfcs-inventory ;;
    operations-06) printf '#!/bin/sh\ntouch /tmp/lfcs-once-ran\n' >/usr/local/bin/lfcs-once; chmod 0755 /usr/local/bin/lfcs-once ;;
    operations-07) sysctl -q -w vm.swappiness=30 ;;
    operations-08) apt-get install -y --no-install-recommends nginx >/dev/null 2>&1 || true ;;
    day1-mini) cat >/etc/lfcs-lab/day1-mini.txt <<'EOF'
1. Enable and start lfcs-sleeper.
2. Set kernel parameter vm.swappiness to 20 now and persistently.
3. Create /tmp/day1-files listing regular files larger than 8 KiB under /srv/lfcs/search.
4. Schedule /usr/local/bin/lfcs-once once using at.
EOF
      setup_one commands-01; setup_one operations-06 ;;
    networking-01) netexec node1 ip addr del 10.10.1.10/24 dev eth0; netexec node1 ip addr add 10.10.1.10/28 dev eth0 ;;
    networking-02) netexec node2 ip route del default; cat >/etc/netplan/90-lfcs-node2.yaml <<'EOF'
network:
  version: 2
EOF
      ;;
    networking-03) netexec node3 ip route replace default via 10.10.3.254 ;;
    networking-04) netexec node1 ip -6 addr flush dev eth0 scope global; netexec node1 ip -6 route del default 2>/dev/null || true ;;
    networking-05) ip link del lfcs-dummy0 >/dev/null 2>&1 || true ;;
    networking-06) cat >/etc/netplan/91-lfcs-dummy.yaml <<'EOF'
network:
 version: 2
  ethernets:
    npdummy0:
      addresses: [198.51.100.20/33]
EOF
      ;;
    networking-07) sed -i '/api.internal/d' /etc/netns/node1/hosts ;;
    networking-08)
      setup_sshd node2 22
      chmod 0777 /home/student/.ssh/authorized_keys
      sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/lfcs-lab/sshd-node2.conf
      stop_pid "$RUN/sshd-node2.pid"
      LFCS_LAB_PID=sshd-node2.pid netexec node2 /usr/sbin/sshd -D -e -f /etc/lfcs-lab/sshd-node2.conf >"$RUN/sshd-node2.log" 2>&1 &
      echo $! >"$RUN/sshd-node2.pid"
      for _ in {1..200}; do
        netexec node2 ss -lntH 'sport = :22' | grep -q . && break
        kill -0 "$(cat "$RUN/sshd-node2.pid")" 2>/dev/null || return 1
        sleep 0.05
      done
      netexec node2 ss -lntH 'sport = :22' | grep -q . ;;
    networking-09) groupadd -f remoteops; usermod -aG remoteops student; setup_sshd node3 2222 yes ;;
    networking-10) printf '[Time]\nNTP=invalid.time.local\n' >/etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf; systemctl restart systemd-timesyncd >/dev/null 2>&1 || true ;;
    networking-11)
      stop_pid "$RUN/node2-http.pid"
      printf 'node2-ready\n' >/srv/lfcs/node2/index.html
      LFCS_LAB_PID=node2-http.pid netexec node2 python3 -m http.server 8083 --bind 127.0.0.1 --directory /srv/lfcs/node2 >"$RUN/node2-http.log" 2>&1 &
      echo $! >"$RUN/node2-http.pid"
      for _ in {1..200}; do
        netexec node2 curl --max-time 1 -fsS http://127.0.0.1:8083/ >/dev/null 2>&1 && break
        kill -0 "$(cat "$RUN/node2-http.pid")" 2>/dev/null || return 1
        sleep 0.05
      done
      netexec node2 curl --max-time 1 -fsS http://127.0.0.1:8083/ >/dev/null ;;
    networking-12) netexec node1 ip route add 203.0.113.0/24 via 10.10.1.254 2>/dev/null || true; rm -f /etc/netplan/90-lfcs-node1.yaml ;;
    day2-mini) cat >/etc/lfcs-lab/day2-mini.txt <<'EOF'
1. Restore node1 IPv4 prefix /24 and connectivity to node2.
2. Make api.internal resolve to node2 from node1.
3. Add a persistent route on node1 for 203.0.113.0/24 through router1.
4. Ensure systemd-timesyncd uses time.cloudflare.com as its primary NTP server.
EOF
      ;;
    advanced-01)
      LFCS_LAB_PID=advanced-01-9090.pid netexec node2 python3 -m http.server 9090 --bind 0.0.0.0 --directory /srv/lfcs/node2 >"$RUN/advanced-01-9090.log" 2>&1 &
      echo $! >"$RUN/advanced-01-9090.pid"
      for _ in {1..100}; do
        netexec node2 ss -lntH 'sport = :9090' | grep -q . && break
        kill -0 "$(cat "$RUN/advanced-01-9090.pid")" 2>/dev/null || return 1
        sleep 0.02
      done
      netexec node2 ss -lntH 'sport = :9090' | grep -q .
      netexec router1 iptables -P FORWARD DROP
      netexec router1 iptables -A FORWARD -p tcp --dport 9090 -j ACCEPT ;;
    advanced-02) iptables -N LFCS_HOST; iptables -A INPUT -j LFCS_HOST; iptables -A LFCS_HOST -s 10.10.1.0/24 -p tcp --dport 8093 -j ACCEPT ;;
    advanced-03) netexec router1 sysctl -q -w net.ipv4.ip_forward=0 ;;
    advanced-04) netexec router1 iptables -t nat -A PREROUTING -p tcp --dport 8181 -j DNAT --to-destination 10.10.2.10:8080; netexec router1 iptables -P FORWARD DROP ;;
    advanced-05) ip link add br-lfcs type bridge; ip link add br-port1 type dummy; ip link add br-port2 type dummy; ip link set br-port1 master br-lfcs ;;
    advanced-06) modprobe bonding; ip link add lfcs-bond0 type bond mode balance-rr; ip link add lfcs-bond-a type dummy; ip link add lfcs-bond-b type dummy; ip link set lfcs-bond-a master lfcs-bond0; ip addr add 172.21.0.10/24 dev lfcs-bond-a ;;
    advanced-07) mkdir -p /etc/nginx/sites-available; cat >/etc/nginx/sites-available/lfcs-proxy <<'EOF'
server { listen 8088; location / { proxy_pass http://10.10.2.10:8088; } }
EOF
      ln -sf /etc/nginx/sites-available/lfcs-proxy /etc/nginx/sites-enabled/lfcs-proxy; systemctl enable --now nginx >/dev/null 2>&1 || true ;;
    advanced-08) cat >/etc/nginx/sites-available/lfcs-lb <<'EOF'
upstream lfcs_backends { server 10.10.2.10:8080; server 10.10.3.10:8081; }
server { listen 8089; location / { proxy_pass http://lfcs_backends; } }
EOF
      ln -sf /etc/nginx/sites-available/lfcs-lb /etc/nginx/sites-enabled/lfcs-lb; systemctl enable --now nginx >/dev/null 2>&1 || true ;;
    advanced-09) mkdir -p /srv/lfcs/share; printf '/srv/lfcs/shrae 10.10.1.0/24(ro,sync,no_subtree_check)\n' >>/etc/exports; systemctl enable --now nfs-server >/dev/null 2>&1 || true; exportfs -ra >/dev/null 2>&1 || true ;;
    advanced-10) base_network; setup_sshd node2 22; mkdir -p /mnt/lfcs/sshfs; chown student:student /mnt/lfcs/sshfs /srv/lfcs/keys/exam; chmod 0644 /srv/lfcs/keys/exam ;;
    advanced-11) mkdir -p /mnt/lfcs/auto /srv/lfcs/share /etc/exports.d; printf '/srv/lfcs/share 127.0.0.1(rw,sync,no_subtree_check,insecure)\n' >/etc/exports.d/lfcs.exports; exportfs -ra >/dev/null 2>&1 || true; systemctl enable --now nfs-server autofs >/dev/null 2>&1 || true ;;
    advanced-12)
      mkdir -p /mnt/lfcs/nbd /etc/nbd-server/conf.d
      truncate -s 96M /var/lib/lfcs-disks/nbd.img
      mkfs.ext4 -F -L LFCS_NBD /var/lib/lfcs-disks/nbd.img >/dev/null
      chown nbd:nbd /var/lib/lfcs-disks/nbd.img
      cat >/etc/nbd-server/conf.d/lfcs-disk.conf <<'EOF'
[lfcs-disk]
    exportname = /var/lib/lfcs-disks/nbd.img
    readonly = false
EOF
      modprobe nbd max_part=8 >/dev/null 2>&1 || true
      systemctl reset-failed nbd-server >/dev/null 2>&1 || true
      systemctl enable nbd-server >/dev/null
      systemctl restart nbd-server >/dev/null
      for _ in {1..100}; do
        systemctl is-active --quiet nbd-server &&
          nbd-client -l localhost 2>/dev/null | grep -qx lfcs-disk && break
        sleep 0.02
      done
      systemctl is-active --quiet nbd-server &&
        nbd-client -l localhost 2>/dev/null | grep -qx lfcs-disk ;;
    opsusers-01) groupadd analytics; groupadd deploy; useradd -m -G analytics dana ;;
    opsusers-02) groupadd projects ;;
    opsusers-03) groupadd reviewers; useradd -m reviewer1; mkdir -p /srv/lfcs/review; touch /srv/lfcs/review/existing; chown root:root /srv/lfcs/review /srv/lfcs/review/existing; chmod 0770 /srv/lfcs/review ;;
    opsusers-04) : ;;
    opsusers-05) : ;;
    opsusers-06) mkdir -p /srv/lfcs/container; printf 'basil-ready\n' >/srv/lfcs/container/index.html; docker run -d --name web-basil -v /srv/lfcs/container:/usr/share/nginx/html:ro nginx:alpine >/dev/null ;;
    opsusers-07) mkdir -p /srv/lfcs/mint /srv/lfcs/wrong-mint; printf 'mint-ready\n' >/srv/lfcs/mint/status; docker run -d --name web-mint -v /srv/lfcs/wrong-mint:/data nginx:alpine >/dev/null ;;
    opsusers-08) printf 'deb http://invalid.lfcs.invalid/ubuntu noble main\n' >/etc/apt/sources.list.d/lfcs-broken.list ;;
    opsusers-09) mkdir -p /srv/selinux-web ;;
    opsusers-10) sed -i -E 's/^[[:space:]]*hosts:.*/hosts:          files/' /etc/nsswitch.conf ;;
    opsusers-11) printf '#!/bin/sh\nexec sleep infinity\n' >/usr/local/bin/mint-agent; chmod 0755 /usr/local/bin/mint-agent; cat >/etc/systemd/system/mint-agent.service <<'EOF'
[Unit]
Description=Mint agent
[Service]
ExecStart=/usr/local/bin/mint-agent
[Install]
WantedBy=multi-user.target
EOF
      systemctl daemon-reload ;;
    opsusers-12) mkdir -p /srv/lfcs; cat >/srv/lfcs/domain.xml <<'EOF'
<domain type='kvm'><name>lfcs-guest</name><memory unit='MiB'>512</memory><metadata><autostart>disabled</autostart></metadata></domain>
EOF
      ;;
    day4-mini) cat >/etc/lfcs-lab/day4-mini.txt <<'EOF'
1. Add dana to deploy without removing analytics membership.
2. Set a default ACL granting reviewers rw access under /srv/lfcs/review.
3. Enable and start mint-agent.
4. Set student's persistent soft/hard nofile limits to 4096/8192.
EOF
      setup_one opsusers-01; setup_one opsusers-03; setup_one opsusers-11 ;;
    storage-01) : ;;
    storage-02) : ;;
    storage-03) : ;;
    storage-04) make_lvm ext4 lfcs_extend data 160M /mnt/lfcs/lvm; printf 'preserve-me\n' >/mnt/lfcs/lvm/sentinel; lvextend -L +64M /dev/lfcs_extend/data >/dev/null ;;
    storage-05) make_lvm xfs lfcs_xfs logs 320M /mnt/lfcs/xfs ;;
    storage-06) : ;;
    storage-07) mkfs.ext4 -F -L LFCS_DATA /dev/lfcs-disk1 >/dev/null; uuid=$(blkid -s UUID -o value /dev/lfcs-disk1); printf 'UUID=00000000-0000-0000-0000-000000000000 /mnt/lfcs/data xfs defaults 0 2 # LFCS-LAB\n' >>/etc/fstab; printf '%s\n' "$uuid" >"$STATE/storage-07.uuid" ;;
    storage-08) mkfs.ext4 -F -N 256 /dev/lfcs-disk3 >/dev/null; mount /dev/lfcs-disk3 /mnt/lfcs/data; mkdir -p /mnt/lfcs/data/{generated,keep}; printf keep >/mnt/lfcs/data/keep/sentinel; for n in $(seq 1 220); do : >"/mnt/lfcs/data/generated/f$n" || break; done ;;
    storage-09) mkdir -p /var/log/lfcs-leak; nohup env LFCS_LAB_PID=leak.pid bash -c 'exec 9>/var/log/lfcs-leak/huge.log; fallocate -l 24M /var/log/lfcs-leak/huge.log; rm /var/log/lfcs-leak/huge.log; exec sleep 10000' </dev/null >/dev/null 2>&1 & echo $! >"$RUN/leak.pid" ;;
    storage-10) setup_git ;;
    storage-11) mkdir -p /etc/lfcs/tls ;;
    storage-12) systemctl stop nginx >/dev/null 2>&1 || true; mkdir -p /etc/lfcs/tls; openssl req -x509 -newkey rsa:2048 -nodes -subj /CN=wrong.lfcs.internal -days 2 -keyout /etc/lfcs/tls/server.key -out /etc/lfcs/tls/server.crt >/dev/null 2>&1; chmod 0644 /etc/lfcs/tls/server.key; cat >/etc/nginx/sites-available/lfcs-tls <<'EOF'
server { listen 8443 ssl; ssl_certificate /etc/lfcs/tls/server.crt; ssl_certificate_key /etc/lfcs/tls/missing.key; location / { return 200 "secure-ready\n"; } }
EOF
      ln -sf /etc/nginx/sites-available/lfcs-tls /etc/nginx/sites-enabled/lfcs-tls ;;
    day5-readiness) cat >/etc/lfcs-lab/day5-readiness.txt <<'EOF'
1. Create an ext4 filesystem labeled READY on /dev/lfcs-disk1 and mount it persistently at /mnt/lfcs/data.
2. Enable 96 MiB persistent swap on /dev/lfcs-disk3.
3. Merge feature/banner into main in /srv/lfcs/repo, preserving both required lines.
4. Create a 30-day certificate for ready.lfcs.internal with a mode-0600 key under /etc/lfcs/tls.
EOF
      setup_git; mkdir -p /etc/lfcs/tls ;;
    *) /usr/local/lib/lfcs/extended-engine.py setup "$id" ;;
  esac
}

make_lvm() {
  local fs=$1 vg=$2 lv=$3 size=$4 mp=$5
  pvcreate -ff -y /dev/lfcs-disk1 >/dev/null
  vgcreate "$vg" /dev/lfcs-disk1 >/dev/null
  lvcreate -L "$size" -n "$lv" "$vg" >/dev/null
  if [[ $fs == xfs ]]; then mkfs.xfs -f -m crc=0 "/dev/$vg/$lv" >/dev/null; else mkfs.ext4 -F "/dev/$vg/$lv" >/dev/null; fi
  mkdir -p "$mp"; mount "/dev/$vg/$lv" "$mp"
}

setup_git() {
  local GIT_AUTHOR_DATE=2026-01-01T00:00:00Z GIT_COMMITTER_DATE=2026-01-01T00:00:00Z
  export GIT_AUTHOR_DATE GIT_COMMITTER_DATE
  mkdir -p /srv/lfcs/repo; git -C /srv/lfcs/repo init -q -b main
  git -C /srv/lfcs/repo config user.email student@lfcs.internal; git -C /srv/lfcs/repo config user.name Student
  printf 'Base\n' >/srv/lfcs/repo/banner.txt; git -C /srv/lfcs/repo add .; git -C /srv/lfcs/repo commit -qm base
  git -C /srv/lfcs/repo switch -qc feature/banner; printf 'Base\nNetworking\n' >/srv/lfcs/repo/banner.txt; git -C /srv/lfcs/repo commit -qam networking
  git -C /srv/lfcs/repo switch -q main; printf 'Base\nOperations\n' >/srv/lfcs/repo/banner.txt; git -C /srv/lfcs/repo commit -qam operations
  chown -R student:student /srv/lfcs/repo
}

grade_one() {
  local id=$1
  case "$id" in
    commands-01)
      check "report exists" test -f /tmp/lfcs-report
      check "report contains exactly the qualifying files" bash -c "diff -u <(printf '/srv/lfcs/search/a/alpha\\n/srv/lfcs/search/b/beta\\n') /tmp/lfcs-report"
      check "report is sorted and unique" bash -c "cmp -s <(sort -u /tmp/lfcs-report) /tmp/lfcs-report" ;;
    commands-02)
      check "error report contains both ERROR records only" bash -c "test \"\$(wc -l </tmp/lfcs-errors)\" -eq 2 && ! grep -v '^ERROR' /tmp/lfcs-errors"
      check "xz archive is valid" tar -tJf /tmp/lfcs-logs.tar.xz
      check "archive contains report and config" bash -c "tar -tJf /tmp/lfcs-logs.tar.xz | grep -q 'lfcs-errors' && tar -tJf /tmp/lfcs-logs.tar.xz | grep -q 'config/app.conf'" ;;
    operations-01)
      check "acorn-api is active" systemctl is-active --quiet acorn-api
      check "acorn-api is enabled" systemctl is-enabled --quiet acorn-api
      check "service uses the valid executable" bash -c "systemctl show -p ExecStart acorn-api --value | grep -q /usr/local/bin/acorn-api"
      check "restart-on-failure is configured" bash -c "systemctl show -p Restart acorn-api --value | grep -Eq 'on-failure|always'" ;;
    operations-02)
      check "report-writer unit exists" test -f /etc/systemd/system/report-writer.service
      check "report-writer is active" systemctl is-active --quiet report-writer
      check "report-writer is enabled" systemctl is-enabled --quiet report-writer
      check "unit uses restart-on-failure" bash -c "systemctl show report-writer -p Restart --value | grep -Eq 'on-failure|always'"
      check "service has written output" test -s /var/log/report-writer.log ;;
    operations-03)
      check "loaded unit uses cedar-worker-v2" bash -c "systemctl show cedar-worker -p ExecStart --value | grep -q cedar-worker-v2"
      check "v2 worker is running" bash -c "test \"\$(cat /run/cedar-version 2>/dev/null)\" = v2"
      check "cedar-worker remains active and enabled" bash -c "systemctl is-active --quiet cedar-worker && systemctl is-enabled --quiet cedar-worker" ;;
    operations-04)
      check "runaway maple workload is stopped" bash -c "p=\$(cat $RUN/runaway.pid 2>/dev/null || echo 0); ! kill -0 \"\$p\" 2>/dev/null"
      check "birch-worker nice value is 10" bash -c "test \"\$(ps -o ni= -p \$(cat $RUN/birch.pid) | tr -d ' ')\" = 10"
      check "unrelated control process remains" kill -0 "$(cat "$RUN/control.pid" 2>/dev/null || echo 0)" ;;
    operations-05)
      check "cron file has safe permissions" bash -c "test \"\$(stat -c %a /etc/cron.d/lfcs-inventory)\" = 644"
      check "job runs every five minutes as root" grep -Eq '^\*/5 \* \* \* \* +root +/usr/local/bin/lfcs-inventory' /etc/cron.d/lfcs-inventory ;;
    operations-06)
      check "one-time job is queued for student" bash -c "atq | grep -q student"
      check "queued job invokes the requested absolute program" bash -c "atq | awk '{print \$1}' | while read j; do at -c \"\$j\"; done | grep -q /usr/local/bin/lfcs-once" ;;
    operations-07)
      check "runtime swappiness is 15" test "$(sysctl -n vm.swappiness)" = 15
      check "swappiness is persistent" grep -RqsE '^\s*vm\.swappiness\s*=\s*15\s*$' /etc/sysctl.conf /etc/sysctl.d ;;
    operations-08)
      check "nginx package is installed" dpkg-query -W nginx
      check "nginx is active and enabled" bash -c "systemctl is-active --quiet nginx && systemctl is-enabled --quiet nginx"
      check "nginx configuration is valid" nginx -t
      check "port 8091 returns requested text" bash -c "curl -fsS http://127.0.0.1:8091 | grep -q day1-ready" ;;
    day1-mini)
      check "sleeper service active and enabled" bash -c "systemctl is-active --quiet lfcs-sleeper && systemctl is-enabled --quiet lfcs-sleeper"
      check "swappiness 20 runtime and persistent" bash -c "test \"\$(sysctl -n vm.swappiness)\" = 20 && grep -RqsE '^ *vm.swappiness *= *20' /etc/sysctl.conf /etc/sysctl.d"
      check "file report is present" test -s /tmp/day1-files
      check "one-time work is queued" bash -c "atq | grep -q student" ;;
    networking-01)
      check "node1 has 10.10.1.10/24" netexec node1 bash -c "ip -4 -o addr show dev eth0 | grep -q '10.10.1.10/24'"
      check "node1 reaches node2" netexec node1 ping -c1 -W1 10.10.2.10
      check "node1 default route remains" netexec node1 bash -c "ip route show default | grep -q 10.10.1.1" ;;
    networking-02)
      check "node2 reaches node3 subnet" netexec node2 ping -c1 -W1 10.10.3.10
      check "specific runtime route uses router1" netexec node2 python3 -c '
import json, subprocess
routes=json.loads(subprocess.check_output(["ip","-j","-4","route","show","exact","10.10.3.0/24"]))
raise SystemExit(not any(r.get("dst")=="10.10.3.0/24" and r.get("gateway")=="10.10.2.1" and r.get("dev")=="eth0" for r in routes))'
      check "node2 connected route remains" netexec node2 bash -c "ip -4 route show exact 10.10.2.0/24 | grep -q 'dev eth0.*scope link'"
      check "persistent route is recorded" python3 -c '
import ipaddress, yaml
with open("/etc/netplan/90-lfcs-node2.yaml") as f: network=yaml.safe_load(f).get("network", {})
found=False
for section in network.values():
    if not isinstance(section, dict): continue
    for interface in section.values():
        if not isinstance(interface, dict): continue
        for route in interface.get("routes", []):
            try: destination=ipaddress.ip_network(str(route.get("to")), strict=False)
            except ValueError: continue
            if str(destination)=="10.10.3.0/24" and str(route.get("via"))=="10.10.2.1": found=True
raise SystemExit(not found)'
      check "Netplan configuration validates" netplan generate ;;
    networking-03)
      check "default gateway is router1" netexec node3 bash -c "ip route show default | grep -q 'via 10.10.3.1'"
      check "node3 reaches node1" netexec node3 ping -c1 -W1 10.10.1.10
      check "node3 reaches node2" netexec node3 ping -c1 -W1 10.10.2.10 ;;
    networking-04)
      check "node1 has requested global IPv6 address" netexec node1 bash -c "ip -6 addr show dev eth0 | grep -q 'fd10:10:1::10/64'"
      check "node1 has an IPv6 default route" netexec node1 bash -c "ip -6 route show default | grep -q 'fd10:10:1::1'"
      check "node1 reaches node3 over IPv6" netexec node1 ping -6 -c4 -W2 fd10:10:3::10 ;;
    networking-05)
      check "NetworkManager profile exists" bash -c "nmcli -t -f NAME con show | grep -qx lfcs-dummy"
      check "dummy interface has requested address" bash -c "ip -4 addr show lfcs-dummy0 | grep -q '192.0.2.10/24'"
      check "profile never supplies a default route" bash -c "test \"\$(nmcli -g ipv4.never-default con show lfcs-dummy)\" = yes" ;;
    networking-06)
      check "Netplan YAML generates successfully" netplan generate
      check "dummy address is represented" grep -Eq '198\.51\.100\.20/24' /etc/netplan/91-lfcs-dummy.yaml
      check "npdummy0 is defined" grep -q npdummy0 /etc/netplan/91-lfcs-dummy.yaml ;;
    networking-07)
      check "direct IP connectivity still works" netexec node1 ping -c1 -W1 10.10.2.10
      check "api.internal resolves correctly" netexec node1 bash -c "getent hosts api.internal | grep -q 10.10.2.10" ;;
    networking-08)
      check "authorized key is installed" grep -qF "$(cat /srv/lfcs/keys/exam.pub)" /home/student/.ssh/authorized_keys
      check "SSH permissions are strict" bash -c "test \"\$(stat -c %a /home/student/.ssh)\" = 700 && test \"\$(stat -c %a /home/student/.ssh/authorized_keys)\" = 600"
      check "password authentication is disabled" bash -c "sshd -T -f /etc/lfcs-lab/sshd-node2.conf -C user=student,host=node2,addr=10.10.1.10 | grep -qx 'passwordauthentication no'"
      check "key authentication works" bash -c "for i in {1..20}; do ip netns exec node1 ssh -i /srv/lfcs/keys/exam -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=2 student@10.10.2.10 true 2>/dev/null && exit 0; sleep 0.1; done; exit 1" ;;
    networking-09)
      check "node3 SSH config is valid" /usr/sbin/sshd -t -f /etc/lfcs-lab/sshd-node3.conf
      check "node3 SSH listens on 2223" bash -c "for i in {1..20}; do ip netns exec node3 ss -lntH 'sport = :2223' | grep -q . && exit 0; sleep 0.1; done; exit 1"
      check "listener belongs to sshd in node3's network namespace" bash -c '
        pid=$(ip netns exec node3 ss -lntp "sport = :2223" | sed -n "s/.*pid=\([0-9][0-9]*\).*/\1/p" | head -1)
        test -n "$pid" && test "$(stat -Lc %i "/proc/$pid/ns/net")" = "$(stat -Lc %i /var/run/netns/node3)" && tr "\0" " " <"/proc/$pid/cmdline" | grep -q /etc/lfcs-lab/sshd-node3.conf
      '
      check "remoteops is the effective access group" bash -c "sshd -T -f /etc/lfcs-lab/sshd-node3.conf -C user=student,host=node3,addr=10.10.1.10 | grep -qx 'allowgroups remoteops'"
      check "public-key authentication is enabled" grep -Eqi '^PubkeyAuthentication +yes' /etc/lfcs-lab/sshd-node3.conf ;;
    networking-10)
      check "timesyncd configuration uses requested server" bash -c "systemd-analyze cat-config systemd/timesyncd.conf | awk -F= '/^NTP=/{value=\$2} END{gsub(/^[[:space:]]+|[[:space:]]+\$/,\"\",value); split(value,servers,/[[:space:]]+/); exit !(servers[1]==\"time.cloudflare.com\")}'"
      check "timesyncd configuration parses" systemd-analyze verify /usr/lib/systemd/system/systemd-timesyncd.service
      check "timesyncd is active and enabled" bash -c "systemctl is-active --quiet systemd-timesyncd && systemctl is-enabled --quiet systemd-timesyncd" ;;
    networking-11)
      check "node2 listens on all addresses at 8084" bash -c "for i in {1..20}; do ip netns exec node2 ss -lnt | grep -Eq '0.0.0.0:8084|\\*:8084' && exit 0; sleep 0.1; done; exit 1"
      check "node1 receives node2-ready" bash -c "for i in {1..20}; do ip netns exec node1 curl -fsS --max-time 2 http://10.10.2.10:8084 2>/dev/null | grep -q node2-ready && exit 0; sleep 0.1; done; exit 1" ;;
    networking-12)
      check "specific runtime route uses router1" netexec node1 bash -c "ip route get 203.0.113.1 | grep -q 'via 10.10.1.1'"
      check "normal default route remains" netexec node1 bash -c "ip route show default | grep -q 'via 10.10.1.1'"
      check "persistent route is recorded" bash -c "grep -q '203\.0\.113\.0/24' /etc/netplan/90-lfcs-node1.yaml && grep -q '10\.10\.1\.1' /etc/netplan/90-lfcs-node1.yaml" ;;
    day2-mini)
      check "node1 IPv4 is correct" netexec node1 bash -c "ip addr show eth0 | grep -q 10.10.1.10/24"
      check "api.internal resolves" netexec node1 bash -c "getent hosts api.internal | grep -q 10.10.2.10"
      check "specific route works" netexec node1 bash -c "ip route get 203.0.113.1 | grep -q 10.10.1.1"
      check "timesyncd source configured" bash -c "systemd-analyze cat-config systemd/timesyncd.conf | grep -q time.cloudflare.com" ;;
    advanced-01)
      check "router1 FORWARD policy is drop" netexec router1 bash -c "iptables -S FORWARD | grep -qx -- '-P FORWARD DROP'"
      check "node1 reaches node2 TCP 8080" netexec node1 nc -z -w2 10.10.2.10 8080
      check "node2 TCP 9090 probe endpoint is locally reachable" netexec node2 nc -z -w2 127.0.0.1 9090
      check "no FORWARD accept rule permits TCP 9090" bash -c "! ip netns exec router1 iptables-save | awk '\$1==\"-A\" && \$2==\"FORWARD\" && /--dport 9090/ && /-j ACCEPT/ {bad=1} END{exit !bad}'"
      check "TCP 9090 is dropped by the firewall despite a live endpoint" bash -c '
        before=$(ip netns exec router1 iptables -L FORWARD -nvx | sed -n "1s/.*policy DROP \([0-9][0-9]*\) packets.*/\1/p")
        ! ip netns exec node1 nc -z -w1 10.10.2.10 9090
        after=$(ip netns exec router1 iptables -L FORWARD -nvx | sed -n "1s/.*policy DROP \([0-9][0-9]*\) packets.*/\1/p")
        test -n "$before" && test -n "$after" && test "$after" -gt "$before"
      ' ;;
    advanced-02)
      check "lab host firewall chain exists" iptables -S LFCS_HOST
      check "8092 accept rule matches node1 source" bash -c "iptables-save | grep -Eq 'LFCS_HOST.*10.10.1.0/24.*8092.*ACCEPT'"
      check "other LFCS sources have a reject or drop rule" bash -c "iptables-save | grep -Eq 'LFCS_HOST.*8092.*(DROP|REJECT)'"
      check "no over-broad 8092 accept exists" bash -c "! iptables-save | awk '\$1==\"-A\" && \$2==\"LFCS_HOST\" && /--dport 8092/ && /-j ACCEPT/ && !/ -s 10.10.1.0\\/24 / {bad=1} END{exit !bad}'" ;;
    advanced-03)
      check "router1 IPv4 forwarding enabled" test "$(netexec router1 sysctl -n net.ipv4.ip_forward)" = 1
      check "masquerade rule exists for node1 subnet and eth0" bash -c "ip netns exec router1 iptables-save -t nat | grep -Eq -- '-A POSTROUTING .*10.10.1.0/24.*-o eth0.*-j MASQUERADE'"
      /usr/local/lib/lfcs/extended-engine.py grade iptables-06 | grep -E '^(PASS|FAIL)\|(node1 traffic|node2 out-of-scope)' ;;
    advanced-04)
      check "DNAT maps 8181 to node2 backend" bash -c "ip netns exec router1 iptables-save -t nat | grep -Eq '8181.*DNAT.*10.10.2.10:8080'"
      check "forwarding permits translated traffic" netexec node1 bash -c "curl -fsS --max-time 2 http://10.10.1.1:8181 | grep -q backend=node2"
      check "return path permits established traffic" bash -c "ip netns exec router1 iptables-save | grep -q -- '--ctstate RELATED,ESTABLISHED.*-j ACCEPT'"
      check "FORWARD has no unconditional accept" bash -c "! ip netns exec router1 iptables-save | grep -Eq '^-A FORWARD -j ACCEPT$'" ;;
    advanced-05)
      check "br-lfcs is a Linux bridge" test -d /sys/class/net/br-lfcs/bridge
      check "bridge has requested IPv4 address and prefix" bash -c "ip -o -4 addr show dev br-lfcs | awk '\$4==\"172.20.0.1/24\" {ok=1} END {exit !ok}'"
      check "br-port1 is attached to br-lfcs" bash -c "test \"\$(basename \"\$(readlink -f /sys/class/net/br-port1/master 2>/dev/null)\")\" = br-lfcs"
      check "br-port2 is attached to br-lfcs" bash -c "test \"\$(basename \"\$(readlink -f /sys/class/net/br-port2/master 2>/dev/null)\")\" = br-lfcs"
      check "bridge and both members are administratively up" bash -c 'for d in br-lfcs br-port1 br-port2; do test -r "/sys/class/net/$d/flags" || exit 1; flags=$(cat "/sys/class/net/$d/flags"); (( flags & 1 )) || exit 1; done' ;;
    advanced-06)
      check "bond uses active-backup mode" grep -q 'Bonding Mode: fault-tolerance (active-backup)' /proc/net/bonding/lfcs-bond0
      check "both members belong to the bond" bash -c "grep -q 'Slave Interface: lfcs-bond-a' /proc/net/bonding/lfcs-bond0 && grep -q 'Slave Interface: lfcs-bond-b' /proc/net/bonding/lfcs-bond0"
      check "address is on bond" bash -c "ip addr show lfcs-bond0 | grep -q 172.21.0.10/24" ;;
    advanced-07)
      check "nginx configuration validates" nginx -t
      check "reverse proxy returns node2 backend" bash -c "for i in {1..12}; do curl --max-time 3 -fsS http://127.0.0.1:8088 2>/dev/null && exit 0; sleep 0.1; done; exit 1" ;;
    advanced-08)
      check "nginx configuration validates" nginx -t
      check "load balancer reaches node2" bash -c "for i in {1..12}; do curl --max-time 3 -fsS http://127.0.0.1:8089 2>/dev/null || true; sleep 0.1; done | grep -q backend=node2"
      check "load balancer reaches node3" bash -c "for i in {1..12}; do curl --max-time 3 -fsS http://127.0.0.1:8089 2>/dev/null || true; sleep 0.1; done | grep -q backend=node3" ;;
    advanced-09)
      check "requested NFS export is configured and scoped" nfs_export_restricted /srv/lfcs/share 10.10.1.0/24
      check "requested NFS export is active" bash -c "exportfs -v | grep -q /srv/lfcs/share"
      check "NFS service is active" systemctl is-active --quiet nfs-server ;;
    advanced-10)
      check "SSHFS mount is active" findmnt -t fuse.sshfs /mnt/lfcs/sshfs
      check "remote content is readable" sudo -u student grep -q backend=node2 /mnt/lfcs/sshfs/index.html ;;
    advanced-11)
      check "autofs master map is configured" grep -Rqs /mnt/lfcs/auto /etc/auto.master /etc/auto.master.d
      check "indirect map points to requested export" grep -Rqs '/srv/lfcs/share' /etc/auto.*
      check "autofs is active and enabled" bash -c "systemctl is-active --quiet autofs && systemctl is-enabled --quiet autofs"
      check "share automounts on access" bash -c "ls /mnt/lfcs/auto/share >/dev/null && findmnt /mnt/lfcs/auto/share" ;;
    advanced-12)
      check "named NBD export is available" bash -c "systemctl is-active --quiet nbd-server && nbd-client -l localhost 2>/dev/null | grep -qx lfcs-disk"
      check "NBD device is connected to the supplied backing image" bash -c "test \"\$(blockdev --getsize64 /dev/nbd0 2>/dev/null)\" = \"\$(stat -c %s /var/lib/lfcs-disks/nbd.img 2>/dev/null)\" && fuser /var/lib/lfcs-disks/nbd.img >/dev/null 2>&1"
      check "NBD filesystem is ext4" bash -c "test \"\$(blkid -s TYPE -o value /dev/nbd0)\" = ext4"
      check "NBD filesystem is mounted" bash -c "findmnt -rn -S /dev/nbd0 -o TARGET | grep -qx /mnt/lfcs/nbd" ;;
    opsusers-01)
      check "dana remains in analytics" bash -c "id -nG dana | grep -qw analytics"
      check "dana is added to deploy" bash -c "id -nG dana | grep -qw deploy"
      check "dana primary group is unchanged" test "$(id -gn dana)" = dana ;;
    opsusers-02)
      check "contractor has requested UID, group, home, and shell" bash -c "test \"\$(id -u contractor)\" = 1777 && test \"\$(id -gn contractor)\" = projects && getent passwd contractor | grep -q ':1777:.*:/home/contractor:/bin/bash$'"
      check "account expiry is correct" bash -c "chage -l contractor | grep -q 'Sep 15, 2026'"
      check "maximum password age is 14" bash -c "chage -l contractor | grep -q 'Maximum number of days between password change.*14'" ;;
    opsusers-03)
      check "reviewers have access ACL on directory" bash -c "getfacl -cp /srv/lfcs/review | grep -Eq '^group:reviewers:rw[x-]'"
      check "existing file grants reviewers read/write" bash -c "getfacl -cp /srv/lfcs/review/existing | grep -q '^group:reviewers:rw-'"
      check "default ACL is present" bash -c "getfacl -cp /srv/lfcs/review | grep -Eq '^default:group:reviewers:rw[x-]'"
      check "others receive no added access" bash -c "! getfacl -cp /srv/lfcs/review | grep -Eq '^default:other::[rwx]*[rw]'" ;;
    opsusers-04)
      check "soft nofile limit is 4096" awk '$1=="student" && $2=="soft" && $3=="nofile" && $4=="4096" {n++} END{exit !(n==1)}' /etc/security/limits.d/90-lfcs.conf
      check "hard nofile limit is 8192" awk '$1=="student" && $2=="hard" && $3=="nofile" && $4=="8192" {n++} END{exit !(n==1)}' /etc/security/limits.d/90-lfcs.conf ;;
    opsusers-05)
      check "global LFCS_REGION is configured" grep -RqsE '(^|export +)LFCS_REGION=eu-west' /etc/profile /etc/profile.d
      check "student TEAM is configured" grep -Eq '(^|export +)TEAM=operations' /home/student/.profile
      check "TEAM is not system-wide" bash -c "! grep -Rqs 'TEAM=operations' /etc/profile /etc/profile.d" ;;
    opsusers-06)
      check "web-basil is running" bash -c "test \"\$(docker inspect -f '{{.State.Running}}' web-basil)\" = true"
      check "web-basil publishes host TCP 8086" bash -c "docker port web-basil | grep -q '8086'"
      check "published service returns bind-mounted content" bash -c "curl -fsS http://127.0.0.1:8086 | grep -q basil-ready"
      check "correct host path is mounted" bash -c "docker inspect web-basil | grep -q /srv/lfcs/container" ;;
    opsusers-07)
      check "web-mint is running" bash -c "test \"\$(docker inspect -f '{{.State.Running}}' web-mint)\" = true"
      check "correct host path backs /data" bash -c "docker inspect web-mint | grep -q /srv/lfcs/mint"
      check "status file is visible inside container" docker exec web-mint grep -q mint-ready /data/status ;;
    opsusers-08)
      check "lab's broken APT source is corrected" bash -c "! grep -Rqs invalid.lfcs.invalid /etc/apt/sources.list /etc/apt/sources.list.d"
      check "package metadata refresh succeeds" apt-get update
      check "package owner report names iproute2" grep -Eq '(^|:)iproute2($|:| )' /tmp/package-owner ;;
    opsusers-09)
      check "SELinux mode is recorded" bash -c "grep -Eq 'Enforcing|Permissive|Disabled' /tmp/selinux-mode"
      if command -v semanage >/dev/null 2>&1 && selinuxenabled; then check "web context rule exists" bash -c "semanage fcontext -l | grep -E '/srv/selinux-web.*httpd_sys_content_t'"; else check "Ubuntu limitation is recorded" grep -qx UNSUPPORTED /tmp/selinux-fcontext; fi ;;
    opsusers-10)
      check "local passwd lookup works" getent passwd root
      check "local group lookup works" getent group root
      check "DNS host lookup source remains" grep -Eq '^hosts:.*(dns|resolve)' /etc/nsswitch.conf ;;
    opsusers-11)
      check "mint-agent is active" systemctl is-active --quiet mint-agent
      check "mint-agent is enabled" systemctl is-enabled --quiet mint-agent
      check "working executable is unchanged" bash -c "systemctl show mint-agent -p ExecStart --value | grep -q /usr/local/bin/mint-agent" ;;
    opsusers-12)
      check "report exists" test -s /tmp/virsh-report
      check "domain name is recorded" grep -q lfcs-guest /tmp/virsh-report
      check "memory is recorded in MiB" grep -q 512 /tmp/virsh-report
      check "disabled autostart is recorded" grep -qi disabled /tmp/virsh-report ;;
    day4-mini)
      check "dana has both supplementary groups" bash -c "id -nG dana | grep -qw analytics && id -nG dana | grep -qw deploy"
      check "review directory has default ACL" bash -c "getfacl -cp /srv/lfcs/review | grep -q '^default:group:reviewers:'"
      check "mint-agent active and enabled" bash -c "systemctl is-active --quiet mint-agent && systemctl is-enabled --quiet mint-agent"
      check "nofile limits configured" bash -c "awk '\$1==\"student\" && \$2==\"soft\" && \$3==\"nofile\" && \$4==\"4096\" {s=1} \$1==\"student\" && \$2==\"hard\" && \$3==\"nofile\" && \$4==\"8192\" {h=1} END{exit !(s&&h)}' /etc/security/limits.d/90-lfcs.conf" ;;
    storage-01)
      check "GPT partition is approximately 200 MiB" bash -c "test \"\$(lsblk -bnro SIZE /dev/lfcs-disk1 | sed -n '2p')\" -ge 190000000 && test \"\$(lsblk -bnro SIZE /dev/lfcs-disk1 | sed -n '2p')\" -le 220000000"
      check "partition filesystem is ext4 with label" bash -c "p=\$(lsblk -nrpo NAME /dev/lfcs-disk1 | sed -n '2p'); test \"\$(blkid -s TYPE -o value \"\$p\")\" = ext4 && test \"\$(blkid -s LABEL -o value \"\$p\")\" = LFCS_DATA"
      check "filesystem is mounted at requested path" findmnt /mnt/lfcs/data ;;
    storage-02)
      check "filesystem is XFS with requested label" bash -c "test \"\$(blkid -s TYPE -o value /dev/lfcs-disk2)\" = xfs && test \"\$(blkid -s LABEL -o value /dev/lfcs-disk2)\" = LFCS_XFS"
      check "disk2 XFS is mounted at the requested path" bash -c "test \"\$(findmnt -n -o FSTYPE /mnt/lfcs/xfs)\" = xfs && test \"\$(findmnt -n -o MAJ:MIN /mnt/lfcs/xfs)\" = \"\$(lsblk -dn -o MAJ:MIN /dev/lfcs-disk2)\""
      check "fstab uses its UUID" fstab_uuid_entry /dev/lfcs-disk2 /mnt/lfcs/xfs xfs
      check "fstab validates" mount -a ;;
    storage-03)
      check "PV and volume group exist" bash -c "pvs --noheadings -o vg_name /dev/lfcs-disk1 | grep -qw lfcs_vg"
      check "logical volume data is 160 MiB" bash -c "size=\$(lvs --noheadings --units m --nosuffix -o lv_size lfcs_vg/data | awk '{print int(\$1)}'); test \"\$size\" -ge 159 && test \"\$size\" -le 161"
      check "the requested LV has ext4 and is mounted" bash -c "test \"\$(blkid -s TYPE -o value /dev/lfcs_vg/data)\" = ext4 && test \"\$(findmnt -n -o FSTYPE /mnt/lfcs/lvm)\" = ext4 && test \"\$(findmnt -n -o MAJ:MIN /mnt/lfcs/lvm)\" = \"\$(lsblk -dn -o MAJ:MIN /dev/lfcs_vg/data)\""
      check "mount is persistent by UUID" fstab_uuid_entry /dev/lfcs_vg/data /mnt/lfcs/lvm ext4 ;;
    storage-04)
      check "logical volume is extended" bash -c "test \"\$(lvs --noheadings --units m --nosuffix -o lv_size lfcs_extend/data | awk '{print int(\$1)}')\" -ge 220"
      check "ext4 filesystem uses extended space" bash -c "test \"\$(df -BM --output=size /mnt/lfcs/lvm | tail -1 | tr -dc 0-9)\" -ge 190"
      check "sentinel data survives" grep -q preserve-me /mnt/lfcs/lvm/sentinel ;;
    storage-05)
      check "disk2 is a PV in lfcs_xfs" bash -c "pvs --noheadings -o vg_name /dev/lfcs-disk2 | grep -qw lfcs_xfs"
      check "logs LV is extended" bash -c "test \"\$(lvs --noheadings --units m --nosuffix -o lv_size lfcs_xfs/logs | awk '{print int(\$1)}')\" -ge 410"
      check "mounted XFS uses extended space" bash -c "test \"\$(df -BM --output=size /mnt/lfcs/xfs | tail -1 | tr -dc 0-9)\" -ge 340" ;;
    storage-06)
      check "disk3 has swap signature" bash -c "test \"\$(blkid -s TYPE -o value /dev/lfcs-disk3)\" = swap"
      check "swap is active" bash -c "d=\$(readlink -f /dev/lfcs-disk3); swapon --show=NAME --noheadings | xargs -r readlink -f | grep -qx \"\$d\""
      check "swap is persistent by UUID" fstab_uuid_entry /dev/lfcs-disk3 none swap ;;
    storage-07)
      check "fstab uses the real UUID" fstab_uuid_entry /dev/lfcs-disk1 /mnt/lfcs/data ext4
      check "fstab mounts successfully" mount -a
      check "filesystem is mounted at requested path" findmnt /mnt/lfcs/data ;;
    storage-08)
      check "at least 20 percent inodes are free" bash -c "test \"\$(df -Pi /mnt/lfcs/data | awk 'NR==2 {print 100-\$5}' | tr -d %)\" -ge 20"
      check "protected data remains" grep -q keep /mnt/lfcs/data/keep/sentinel ;;
    storage-09)
      check "no deleted-open file remains under leak path" bash -c "! lsof +L1 2>/dev/null | grep -q /var/log/lfcs-leak"
      check "unrelated audit service is not terminated" systemctl is-active --quiet auditd ;;
    storage-10)
      check "main contains feature commit" bash -c "git -c safe.directory=/srv/lfcs/repo -C /srv/lfcs/repo merge-base --is-ancestor feature/banner main"
      check "banner contains Operations and Networking" bash -c "grep -qx Operations /srv/lfcs/repo/banner.txt && grep -qx Networking /srv/lfcs/repo/banner.txt"
      check "working tree is clean" bash -c "test -z \"\$(git -c safe.directory=/srv/lfcs/repo -C /srv/lfcs/repo status --porcelain)\"" ;;
    storage-11)
      check "private key exists and is unencrypted" tls_material_check /etc/lfcs/tls key
      check "private key mode is 0600" tls_material_check /etc/lfcs/tls key_mode
      check "certificate and private key match" tls_material_check /etc/lfcs/tls pair
      check "certificate CN is lfcs.internal" tls_material_check /etc/lfcs/tls pair_cn lfcs.internal
      check "matching certificate remains valid for 29 days" tls_material_check /etc/lfcs/tls complete_cn lfcs.internal 2505600 ;;
    storage-12)
      check "nginx configuration validates" nginx -t
      check "nginx is active" systemctl is-active --quiet nginx
      check "live certificate identity is correct" tls_endpoint_has_identity 127.0.0.1:8443 secure.lfcs.internal
      check "TLS endpoint returns requested response" bash -c "curl -kfsS https://127.0.0.1:8443 | grep -q secure-ready" ;;
    day5-readiness)
      check "READY ext4 is mounted persistently" bash -c "test \"\$(blkid -s LABEL -o value /dev/lfcs-disk1)\" = READY && findmnt /mnt/lfcs/data && fstab_uuid_entry /dev/lfcs-disk1 /mnt/lfcs/data ext4"
      check "persistent swap is active" bash -c "d=\$(readlink -f /dev/lfcs-disk3); swapon --show=NAME --noheadings | xargs -r readlink -f | grep -qx \"\$d\" && fstab_uuid_entry /dev/lfcs-disk3 none swap"
      check "Git feature is merged cleanly" bash -c "git -c safe.directory=/srv/lfcs/repo -C /srv/lfcs/repo merge-base --is-ancestor feature/banner main && test -z \"\$(git -c safe.directory=/srv/lfcs/repo -C /srv/lfcs/repo status --porcelain)\""
      check "readiness certificate is valid" tls_material_check /etc/lfcs/tls complete_host ready.lfcs.internal 2505600 ;;
    *) /usr/local/lib/lfcs/extended-engine.py grade "$id" ;;
  esac
}

case "$MODE" in
  setup) setup_one "$ID" ;;
  reset) reset_one "$ID" ;;
  grade) grade_one "$ID" ;;
  *) echo "usage: scenario-engine.sh setup|reset|grade ID" >&2; exit 2 ;;
esac
