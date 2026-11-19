#!/usr/bin/env bash
set -eu

# QA-only, pre-grader validation.  These checks deliberately use ordinary
# administration tools and observable state instead of calling either grader.
sid=${1:?scenario id required}
net() { ip netns exec "$@"; }
fstab_uuid_entry() {
  local device=$1 target=$2 fstype=$3 required=${4:-} uuid source found_target found_type options option
  uuid=$(blkid -s UUID -o value "$device")
  while read -r source found_target found_type options; do
    source=${source//\"/}
    found_target=${found_target//\"/}
    [[ $source == "UUID=$uuid" && $found_target == "$target" && $found_type == "$fstype" ]] || continue
    for option in ${required//,/ }; do [[ ,$options, == *,$option,* ]] || continue 2; done
    return 0
  done < <(findmnt --fstab --raw -rn -o SOURCE,TARGET,FSTYPE,OPTIONS)
  return 1
}
fstab_target_entry() {
  local target=$1 fstype=$2 required=${3:-} source found_target found_type options option
  while read -r source found_target found_type options; do
    found_target=${found_target//\"/}
    [[ $found_target == "$target" && $found_type == "$fstype" ]] || continue
    for option in ${required//,/ }; do [[ ,$options, == *,$option,* ]] || continue 2; done
    return 0
  done < <(findmnt --fstab --raw -rn -o SOURCE,TARGET,FSTYPE,OPTIONS)
  return 1
}
fstab_source_entry() {
  local expected_source=$1 target=$2 fstype=$3 required=${4:-} source found_target found_type options option
  while read -r source found_target found_type options; do
    source=${source//\"/}; found_target=${found_target//\"/}
    [[ $source == "$expected_source" && $found_target == "$target" && $found_type == "$fstype" ]] || continue
    for option in ${required//,/ }; do [[ ,$options, == *,$option,* ]] || continue 2; done
    return 0
  done < <(findmnt --fstab --raw -rn -o SOURCE,TARGET,FSTYPE,OPTIONS)
  return 1
}
nm_persistent() {
  local name=$1 uuid file
  uuid=$(nmcli -g connection.uuid con show "$name")
  for file in /etc/NetworkManager/system-connections/*.nmconnection; do
    [[ -f $file ]] || continue
    grep -qx "id=$name" "$file" && grep -qx "uuid=$uuid" "$file" && return 0
  done
  grep -RqsE "uuid: *[\"']?$uuid[\"']?$" /etc/netplan &&
    grep -RqsE "name: *[\"']?$name[\"']?$" /etc/netplan &&
    netplan generate
  return
}
tls_complete_pair() {
  local dir=$1 identity=$2 identity_mode=${3:-host} seconds=${4:-2505600}
  local file key cert key_hash cert_hash subject
  local -a keys=() certs=()
  while IFS= read -r -d '' file; do
    openssl pkey -in "$file" -noout </dev/null >/dev/null 2>&1 && keys+=("$file")
    openssl x509 -in "$file" -noout >/dev/null 2>&1 && certs+=("$file")
  done < <(find "$dir" -maxdepth 1 -type f -print0 | sort -z)
  for cert in "${certs[@]}"; do
    cert_hash=$(openssl x509 -in "$cert" -pubkey -noout 2>/dev/null | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')
    for key in "${keys[@]}"; do
      [[ $(stat -c %a "$key" 2>/dev/null) == 600 ]] || continue
      key_hash=$(openssl pkey -in "$key" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')
      [[ $key_hash == "$cert_hash" ]] || continue
      if [[ $identity_mode == cn ]]; then
        subject=$(openssl x509 -in "$cert" -noout -subject -nameopt RFC2253)
        subject=${subject#subject=}
        [[ ,$subject, == *,CN="$identity",* ]] || continue
      else
        openssl verify -CAfile "$cert" -verify_hostname "$identity" "$cert" >/dev/null 2>&1 || continue
      fi
      openssl x509 -in "$cert" -noout -checkend "$seconds" >/dev/null 2>&1 && return 0
    done
  done
  return 1
}
tls_endpoint_identity() {
  local cert rc
  cert=$(mktemp /tmp/lfcs-independent-cert.XXXXXX)
  if ! openssl s_client -connect "$1" -servername "$2" -showcerts </dev/null 2>/dev/null |
      awk '/-----BEGIN CERTIFICATE-----/{copy=1} copy{print} /-----END CERTIFICATE-----/{exit}' >"$cert"; then
    rm -f "$cert"
    return 1
  fi
  openssl verify -CAfile "$cert" -verify_hostname "$2" "$cert" >/dev/null 2>&1
  rc=$?
  rm -f "$cert"
  return "$rc"
}
networking09_nonmember_rejected() {
  local account=qa_ssh_nonmember rc
  userdel -r "$account" >/dev/null 2>&1 || true
  useradd -m -s /bin/bash "$account"
  install -d -o "$account" -g "$account" -m 0700 "/home/$account/.ssh"
  install -o "$account" -g "$account" -m 0600 /srv/lfcs/keys/exam.pub "/home/$account/.ssh/authorized_keys"
  set +e
  ssh -p 2223 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null -i /srv/lfcs/keys/exam "$account"@10.10.3.10 true >/dev/null 2>&1
  rc=$?
  set -e
  userdel -r "$account" >/dev/null 2>&1 || true
  test "$rc" -ne 0
}

case "$sid" in
  commands-01) test "$(sort -u /tmp/lfcs-report)" = $'/srv/lfcs/search/a/alpha\n/srv/lfcs/search/b/beta' ;;
  commands-02) grep -qx 'ERROR|disk' /tmp/lfcs-errors; grep -qx 'ERROR|network' /tmp/lfcs-errors; tar -tJf /tmp/lfcs-logs.tar.xz | grep -q 'config/app.conf' ;;
  operations-01) systemctl is-active --quiet acorn-api; systemctl is-enabled --quiet acorn-api; systemctl show -p Restart --value acorn-api | grep -qx on-failure ;;
  operations-02) systemctl is-active --quiet report-writer; systemctl is-enabled --quiet report-writer; test -s /var/log/report-writer.log ;;
  operations-03) systemctl is-active --quiet cedar-worker; systemctl is-enabled --quiet cedar-worker; grep -qx v2 /run/cedar-version ;;
  operations-04) ! kill -0 "$(cat /run/lfcs-lab/runaway.pid)" 2>/dev/null; test "$(ps -o ni= -p "$(cat /run/lfcs-lab/birch.pid)" | tr -d ' ')" = 10 ;;
  operations-05) grep -Eq '^\*/5 \* \* \* \* root /usr/local/bin/lfcs-inventory$' /etc/cron.d/lfcs-inventory ;;
  operations-06) sudo -u student atq | grep -q .; ! test -e /tmp/lfcs-once-ran ;;
  operations-07) test "$(sysctl -n vm.swappiness)" = 15; sysctl --system 2>/dev/null | grep -q 'vm.swappiness = 15' ;;
  operations-08) systemctl is-active --quiet nginx; systemctl is-enabled --quiet nginx; test "$(curl -fsS http://127.0.0.1:8091/)" = day1-ready ;;
  day1-mini) systemctl is-active --quiet lfcs-sleeper; test "$(sysctl -n vm.swappiness)" = 20; test -s /tmp/day1-files; sudo -u student atq | grep -q . ;;

  networking-01) net node1 ip -4 addr show dev eth0 | grep -q '10.10.1.10/24'; net node1 ping -c1 -W1 10.10.2.10 >/dev/null ;;
  networking-02) net node2 ip route get 10.10.3.10 | grep -q 'via 10.10.2.1'; grep -q '10.10.3.0/24' /etc/netplan/90-lfcs-node2.yaml ;;
  networking-03) net node3 ip route show default | grep -q 'via 10.10.3.1'; net node3 ping -c1 -W1 10.10.1.10 >/dev/null ;;
  networking-04) net node1 ip -6 addr show dev eth0 | grep -q 'fd10:10:1::10/64'; net node1 ping -6 -c4 -W2 fd10:10:3::10 >/dev/null ;;
  networking-05) nmcli -g GENERAL.STATE device show lfcs-dummy0 | grep -q '^100'; ip -4 addr show lfcs-dummy0 | grep -q '192.0.2.10/24' ;;
  networking-06) netplan generate; grep -q '198.51.100.20/24' /etc/netplan/91-lfcs-dummy.yaml ;;
  networking-07) test "$(net node1 getent hosts api.internal | awk 'NR==1{print $1}')" = 10.10.2.10 ;;
  networking-08) net node1 ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /srv/lfcs/keys/exam student@10.10.2.10 true; /usr/sbin/sshd -T -f /etc/lfcs-lab/sshd-node2.conf -C user=student,host=node2,addr=10.10.1.10 | grep -qx 'passwordauthentication no' ;;
  networking-09)
    /usr/sbin/sshd -t -f /etc/lfcs-lab/sshd-node3.conf
    pid=$(net node3 ss -lntp 'sport = :2223' | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)
    test -n "$pid"
    test "$(stat -Lc %i "/proc/$pid/ns/net")" = "$(stat -Lc %i /var/run/netns/node3)"
    tr '\0' ' ' <"/proc/$pid/cmdline" | grep -q /etc/lfcs-lab/sshd-node3.conf
    grep -Eq '^AllowGroups +remoteops$' /etc/lfcs-lab/sshd-node3.conf
    ssh -p 2223 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /srv/lfcs/keys/exam student@10.10.3.10 true
    networking09_nonmember_rejected
    printf 'ls /srv/lfcs/node3\nquit\n' | sftp -q -b - -P 2223 -oBatchMode=yes -oIdentitiesOnly=yes -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null -i /srv/lfcs/keys/exam student@10.10.3.10 ;;
  networking-10) systemctl is-active --quiet systemd-timesyncd; systemd-analyze cat-config systemd/timesyncd.conf | grep -q '^NTP=time.cloudflare.com$' ;;
  networking-11) test "$(net node1 curl -fsS http://10.10.2.10:8084/)" = node2-ready ;;
  networking-12) net node1 ip route get 203.0.113.1 | grep -q 'via 10.10.1.1'; grep -q '203.0.113.0/24' /etc/netplan/90-lfcs-node1.yaml ;;
  nmcli-01) nm_persistent lfcs-cedar; test "$(nmcli -g GENERAL.CONNECTION device show nmcedar0)" = lfcs-cedar; ip -4 -o address show nmcedar0 | grep -qw 198.51.100.20/24; test "$(nmcli -g ipv4.never-default con show lfcs-cedar)" = yes ;;
  nmcli-02) nm_persistent lfcs-aspen; test "$(nmcli -g GENERAL.CONNECTION device show nmaspen0)" = lfcs-aspen; ip route get 198.51.100.1 | grep -q 'via 192.0.2.1 dev nmaspen0'; nmcli -g ipv4.routes con show lfcs-aspen | grep -q 198.51.100.0/24 ;;
  nmcli-03) nm_persistent lfcs-maple; test "$(nmcli -g GENERAL.CONNECTION device show nmaple0)" = lfcs-maple; ip -4 -o address show nmaple0 | grep -qw 203.0.113.30/24; test "$(nmcli -g connection.autoconnect con show lfcs-maple)" = yes; test "$(nmcli -g connection.autoconnect con show lfcs-maple-old)" = no ;;
  day2-mini) net node1 ping -c1 -W1 10.10.2.10 >/dev/null; net node1 getent hosts api.internal | grep -q '^10.10.2.10'; net node1 ip route get 203.0.113.1 | grep -q 'via 10.10.1.1' ;;
  advanced-01)
    net node1 curl --max-time 2 -fsS http://10.10.2.10:8080/ | grep -q 'backend=node2'
    test "$(net router1 iptables -S FORWARD | head -1)" = '-P FORWARD DROP'
    net node2 nc -z -w2 127.0.0.1 9090
    ! net router1 iptables-save | awk '$1=="-A" && $2=="FORWARD" && /--dport 9090/ && /-j ACCEPT/ {bad=1} END{exit !bad}'
    ! net node1 nc -z -w1 10.10.2.10 9090 ;;
  advanced-02) iptables -S LFCS_HOST | grep -q -- '-s 10.10.1.0/24.*--dport 8092.*-j ACCEPT'; iptables -S LFCS_HOST | grep -q -- '--dport 8092.*-j REJECT' ;;
  advanced-03) test "$(net router1 sysctl -n net.ipv4.ip_forward)" = 1; net router1 iptables -t nat -S POSTROUTING | grep -q '10.10.1.0/24.*MASQUERADE' ;;
  advanced-04) net node1 curl --max-time 2 -fsS http://10.10.1.1:8181/ | grep -q 'backend=node2' ;;
  advanced-05) test -d /sys/class/net/br-lfcs/bridge; ip -o -4 addr show br-lfcs | awk '$4=="172.20.0.1/24" {ok=1} END {exit !ok}'; for d in br-lfcs br-port1 br-port2; do flags=$(cat /sys/class/net/$d/flags); (( flags & 1 )); test "$(basename "$(readlink -f /sys/class/net/$d/master 2>/dev/null || true)")" = br-lfcs || test "$d" = br-lfcs; done ;;
  advanced-06) grep -q '^active-backup' /sys/class/net/lfcs-bond0/bonding/mode; ip -4 addr show lfcs-bond0 | grep -q '172.21.0.10/24' ;;
  advanced-07) for _ in {1..20}; do test "$(curl --max-time 2 -fsS http://127.0.0.1:8088/ 2>/dev/null)" = 'backend=node2' && break; sleep 0.05; done; test "$(curl --max-time 2 -fsS http://127.0.0.1:8088/)" = 'backend=node2'; nginx -t ;;
  advanced-08)
    responses=
    for _ in {1..20}; do
      responses=$(for _ in {1..20}; do curl -fsS http://127.0.0.1:8089/; done)
      grep -q 'backend=node2' <<<"$responses" && grep -q 'backend=node3' <<<"$responses" && break
      sleep 0.1
    done
    grep -q 'backend=node2' <<<"$responses"
    grep -q 'backend=node3' <<<"$responses" ;;
  advanced-09) exportfs -s | grep -q '^/srv/lfcs/share  *10.10.1.0/24'; systemctl is-active --quiet nfs-server ;;
  advanced-10) sudo -u student ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /srv/lfcs/keys/exam student@10.10.2.10 true; printf 'ls /srv/lfcs/node2\nquit\n' | sudo -u student sftp -q -b - -oBatchMode=yes -oIdentitiesOnly=yes -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null -i /srv/lfcs/keys/exam student@10.10.2.10; findmnt -rn /mnt/lfcs/sshfs | grep -q 'fuse.sshfs'; sudo -u student grep -q 'backend=node2' /mnt/lfcs/sshfs/index.html ;;
  advanced-11) systemctl is-active --quiet autofs; test -d /mnt/lfcs/auto/share; findmnt -rn /mnt/lfcs/auto/share >/dev/null ;;
  advanced-12) nbd-client -l localhost | grep -qx lfcs-disk; test "$(blockdev --getsize64 /dev/nbd0)" = "$(stat -c %s /var/lib/lfcs-disks/nbd.img)"; fuser /var/lib/lfcs-disks/nbd.img >/dev/null 2>&1; test "$(findmnt -rn -o FSTYPE /mnt/lfcs/nbd)" = ext4; test "$(findmnt -rn -o SOURCE /mnt/lfcs/nbd)" = /dev/nbd0 ;;

  opsusers-01) id -nG dana | grep -qw analytics; id -nG dana | grep -qw deploy ;;
  opsusers-02) getent passwd contractor | grep -q '^contractor:x:1777:.*:/home/contractor:/bin/bash$'; chage -l contractor | grep -q 'Sep 15, 2026' ;;
  opsusers-03) getfacl -cp /srv/lfcs/review | grep -qx 'group:reviewers:rwx'; getfacl -cp /srv/lfcs/review | grep -qx 'default:group:reviewers:rwx' ;;
  opsusers-04) awk '$1=="student" && $2=="soft" && $3=="nofile" && $4=="4096" {s=1} $1=="student" && $2=="hard" && $3=="nofile" && $4=="8192" {h=1} END{exit !(s&&h)}' /etc/security/limits.d/90-lfcs.conf ;;
  opsusers-05) sudo -iu student env | grep -qx 'LFCS_REGION=eu-west'; sudo -iu student env | grep -qx 'TEAM=operations' ;;
  opsusers-06) test "$(curl -fsS http://127.0.0.1:8086/)" = basil-ready; docker inspect -f '{{.State.Running}}' web-basil | grep -qx true ;;
  opsusers-07) docker exec web-mint cat /data/status | grep -q mint-ready; docker inspect -f '{{.State.Running}}' web-mint | grep -qx true ;;
  opsusers-08) apt-get update -qq; grep -q '^iproute2:' /tmp/package-owner ;;
  opsusers-09) test -s /tmp/selinux-mode; test -s /tmp/selinux-fcontext ;;
  opsusers-10) getent passwd root >/dev/null; getent group root >/dev/null; grep -Eq '^hosts:.*(dns|resolve)' /etc/nsswitch.conf ;;
  opsusers-11) systemctl is-active --quiet mint-agent; systemctl is-enabled --quiet mint-agent ;;
  opsusers-12) test "$(sed -n '1p' /tmp/virsh-report)" = lfcs-guest; test "$(sed -n '2p' /tmp/virsh-report)" = 512 ;;
  day4-mini) id -nG dana | grep -qw deploy; getfacl -cp /srv/lfcs/review | grep -q 'group:reviewers:rwx'; systemctl is-active --quiet mint-agent ;;

  storage-01) test "$(findmnt -rn -o FSTYPE /mnt/lfcs/data)" = ext4; test "$(findmnt -rn -o LABEL /mnt/lfcs/data)" = LFCS_DATA ;;
  storage-02) test "$(findmnt -rn -o FSTYPE /mnt/lfcs/xfs)" = xfs; test "$(findmnt -rn -o MAJ:MIN /mnt/lfcs/xfs)" = "$(lsblk -dnro MAJ:MIN /dev/lfcs-disk2)"; fstab_uuid_entry /dev/lfcs-disk2 /mnt/lfcs/xfs xfs ;;
  storage-03) test "$(lvs --noheadings -o lv_size --units m --nosuffix lfcs_vg/data | awk '{print int($1)}')" -ge 159; test "$(findmnt -rn -o MAJ:MIN /mnt/lfcs/lvm)" = "$(lsblk -dnro MAJ:MIN /dev/lfcs_vg/data)"; fstab_uuid_entry /dev/lfcs_vg/data /mnt/lfcs/lvm ext4 ;;
  storage-04) test "$(findmnt -rn -o FSTYPE /mnt/lfcs/lvm)" = ext4; test "$(df -BM --output=size /mnt/lfcs/lvm | tail -1 | tr -dc 0-9)" -ge 190; grep -q preserve-me /mnt/lfcs/lvm/sentinel ;;
  storage-05) test "$(findmnt -rn -o FSTYPE /mnt/lfcs/xfs)" = xfs; test "$(df -BM --output=size /mnt/lfcs/xfs | tail -1 | tr -dc 0-9)" -ge 340; pvs --noheadings -o vg_name /dev/lfcs-disk2 | grep -qw lfcs_xfs ;;
  storage-06) swapon --noheadings --show=NAME | xargs -r readlink -f | grep -qx "$(readlink -f /dev/lfcs-disk3)"; fstab_uuid_entry /dev/lfcs-disk3 none swap ;;
  storage-07) mount -a; findmnt -rn /mnt/lfcs/data >/dev/null ;;
  storage-08) df -Pi /mnt/lfcs/data | awk 'NR==2{exit !($4/$2>=.20)}'; grep -q keep /mnt/lfcs/data/keep/sentinel ;;
  storage-09) ! kill -0 "$(cat /run/lfcs-lab/leak.pid)" 2>/dev/null; test -d /var/log/lfcs-leak ;;
  storage-10) sudo -u student git -C /srv/lfcs/repo status --porcelain | test ! -s /dev/stdin; grep -qx Operations /srv/lfcs/repo/banner.txt; grep -qx Networking /srv/lfcs/repo/banner.txt ;;
  storage-11) tls_complete_pair /etc/lfcs/tls lfcs.internal cn ;;
  storage-12) nginx -t; tls_endpoint_identity 127.0.0.1:8443 secure.lfcs.internal; curl -kfsS --resolve secure.lfcs.internal:8443:127.0.0.1 https://secure.lfcs.internal:8443/ | grep -q secure-ready ;;
  day5-readiness) findmnt -rn /mnt/lfcs/data >/dev/null; swapon --noheadings --show=NAME | grep -q .; tls_complete_pair /etc/lfcs/tls ready.lfcs.internal host ;;

  sysinfo-01) test "$(cat /tmp/kernel-release)" = "$(uname -r)"; test "$(cat /tmp/default-target)" = "$(systemctl get-default)" ;;
  sysinfo-02) test "$(wc -l </tmp/boot-clock-report)" = 3; test "$(sed -n '3p' /tmp/boot-clock-report)" = "$(cat /proc/sys/kernel/random/boot_id)" ;;
  systemd-04) systemctl is-active --quiet alder-worker; test "$(systemctl show -p User --value alder-worker)" = svc-alder ;;
  systemd-05) systemctl is-active --quiet pine-api; grep -qx production /run/pine-mode ;;
  systemd-06) systemctl is-active --quiet juniper-agent; systemctl is-enabled --quiet juniper-agent; test "$(systemctl show -p Restart --value juniper-agent)" = on-failure ;;
  systemd-07) systemctl is-active --quiet spruce-web; systemctl is-active --quiet spruce-data; test -e /run/spruce-web-ready ;;
  systemd-08) systemctl is-active --quiet hemlock-job; grep -qx green /run/hemlock-result ;;
  cron-02) sudo -u student crontab -l | grep -Eq '^15 7 \* \* 1,3,5 /usr/local/bin/alder-backup --incremental$'; ! test -e /etc/cron.d/alder-backup ;;
  cron-03) test "$(stat -c %a /etc/cron.d/maple-prune)" = 644; grep -Eq '^40 2 1 \* \* root /usr/local/bin/maple-prune$' /etc/cron.d/maple-prune ;;
  cron-04) grep -Eq '^7 +12 +cedar-index +/usr/local/bin/cedar-index$' /etc/anacrontab ;;
  process-02) p=$(sed -n '1p' /tmp/walnut-report); kill -0 "$p"; test "$(ps -o ni= -p "$p" | tr -d ' ')" = 12; test "$(sed -n '3p' /tmp/walnut-report)" = /srv/lfcs/process/walnut.data ;;
  source-01) test -x /usr/bin/leafutil; /usr/bin/leafutil | grep -q 'prefix=/usr ipv6=disabled' ;;
  docker-01) docker inspect -f '{{.State.Running}}' web-fern | grep -qx true; test "$(sed -n '3p' /tmp/web-fern-report)" = 8131 ;;
  docker-02) test "$(curl -fsS http://127.0.0.1:8132/)" = ivy-ready; docker inspect -f '{{.HostConfig.Memory}}' web-ivy | grep -qx 100663296 ;;
  timesync-01) systemctl is-active --quiet systemd-timesyncd; systemd-analyze cat-config systemd/timesyncd.conf | grep -q '^FallbackNTP=ntp.ubuntu.com$' ;;
  timesync-02) systemctl is-active --quiet systemd-timesyncd; systemd-analyze cat-config systemd/timesyncd.conf | grep -q '^ConnectionRetrySec=30$' ;;
  virt-01) grep -q '^ACTIVE$' /tmp/virt-list; grep -q '^ALL$' /tmp/virt-list; grep -q test /tmp/virt-list ;;
  virt-02) test "$(wc -l </tmp/virt-dominfo)" = 4; test "$(sed -n '1p' /tmp/virt-dominfo)" = test ;;
  virt-03) bash -n /srv/lfcs/virt/lifecycle.sh; grep -q 'virsh.*undefine exam-elm' /srv/lfcs/virt/lifecycle.sh ;;
  virt-04) python3 -c 'import xml.etree.ElementTree as E; r=E.parse("/srv/lfcs/virt/exam-ash.xml").getroot(); assert r.findtext("name")=="exam-ash" and r.findtext("vcpu")=="2" and r.findtext("memory")=="768"'; grep -q "bus='virtio'" /srv/lfcs/virt/exam-ash.xml ;;
  virt-05) python3 -c 'import xml.etree.ElementTree as E; r=E.parse("/srv/lfcs/virt/exam-oak.xml").getroot(); assert r.findtext("vcpu")=="3" and r.findtext("memory")=="1024" and r.findtext("metadata/autostart")=="enabled"'; grep -q exam-oak.qcow2 /srv/lfcs/virt/exam-oak.xml ;;
  virt-06) jq -e '.format=="qcow2" and .["virtual-size"]==67108864' /tmp/exam-maple-info >/dev/null ;;
  virt-07) qemu-img info --output=json /srv/lfcs/virt/exam-willow.qcow2 | jq -e '.["virtual-size"]==117440512' >/dev/null ;;
  virt-08) bash -n /srv/lfcs/virt/create-birch.sh; grep -q -- '--name exam-birch' /srv/lfcs/virt/create-birch.sh ;;
  virt-09) bash -n /srv/lfcs/virt/create-cedar.sh; grep -Eq 'virt-install.*--name(=| +)exam-cedar' /srv/lfcs/virt/create-cedar.sh; grep -Eq -- '--memory(=| +)512.*--vcpus(=| +)1' /srv/lfcs/virt/create-cedar.sh; grep -q -- '--print-xml' /srv/lfcs/virt/create-cedar.sh ;;

  iptables-01) net node2 iptables -C INPUT -p tcp --dport 9121 -j DROP ;;
  iptables-02) net node2 iptables -S INPUT | grep -q -- '-s 10.10.1.0/24.*--dport 9122.*ACCEPT'; net node2 iptables -S INPUT | grep -q -- '--dport 9122.*REJECT' ;;
  iptables-03) net node1 iptables -C OUTPUT -d 10.10.3.10/32 -p tcp --dport 9123 -j REJECT ;;
  iptables-04) test "$(net node2 curl -fsS http://127.0.0.1:8184/)" = node2-ready ;;
  iptables-05) net node1 curl --max-time 2 -fsS http://10.10.1.1:8185/ | grep -q backend=node2 ;;
  iptables-06) net router1 iptables -t nat -S POSTROUTING | grep -q -- '-s 10.10.1.0/24.*-o eth0.*MASQUERADE' ;;
  iptables-07) test "$(net router1 iptables -S FORWARD | head -1)" = '-P FORWARD DROP'; net router1 iptables -S FORWARD | grep -q '10.10.3.10/32.*--dport 9127.*ACCEPT' ;;
  iptables-08) net node2 iptables -S INPUT | awk '/10\.10\.1\.0\/24.*9128.*ACCEPT/{a=NR} /9128.*REJECT/{r=NR} END{exit !(a&&r&&a<r)}' ;;
  iptables-09) iptables -S INPUT | grep -q -- '-j LFCS_PERSIST'; iptables-restore --test </etc/iptables/rules.v4 ;;
  iptables-10) test "$(net router1 iptables -S FORWARD | head -1)" = '-P FORWARD DROP'; net router1 iptables-restore --test </etc/iptables/lfcs-router.v4 ;;
  nginx-01) nginx -t; test "$(curl -fsS http://127.0.0.1:8111/)" = amber-ready ;;
  nginx-02) nginx -t; test "$(curl -fsS http://127.0.0.1:8112/)" = alder-ready ;;
  nginx-03) nginx -t; test "$(curl -fsS -H 'Host: probe.lfcs' http://127.0.0.1:8113/)" = backend=node2 ;;
  nginx-04) nginx -t; test "$(curl -fsS http://127.0.0.1:8114/api/)" = backend=node2; test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8114/)" = 404 ;;
  nginx-05) test "$(curl -fsS http://127.0.0.1:8115/)" = twin-ready; test "$(curl -fsS http://127.0.0.1:8116/)" = twin-ready ;;
  nginx-06) nginx -t; test "$(stat -c %a /etc/lfcs/tls/fern/server.key)" = 600; curl -kfsS https://127.0.0.1:8446/ | grep -q fern-secure ;;
  ssh-match-01) sshd -t -f /etc/lfcs-lab/sshd-match.conf; sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=buildbot,host=x,addr=127.0.0.1 | grep -qx 'passwordauthentication no' ;;
  ssh-match-02) sshd -t -f /etc/lfcs-lab/sshd-match.conf; sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=buildbot,host=x,addr=127.0.0.1 | grep -qx 'forcecommand internal-sftp' ;;
  ssh-match-03) sshd -t -f /etc/lfcs-lab/sshd-match.conf; test "$(cat /tmp/deployer-banner)" = /etc/issue.net ;;

  lvm-01) ! pvs --noheadings -o vg_name /dev/lfcs-disk2 2>/dev/null | grep -qw orchard; grep -q preserve-orchard /mnt/lfcs/orchard/sentinel ;;
  lvm-02) pvs --noheadings -o vg_name /dev/lfcs-disk2 | grep -qw freshfruit; test "$(findmnt -rn -o FSTYPE /mnt/lfcs/crates)" = ext4 ;;
  lvm-03) test "$(lvs --noheadings -o lv_size --units m --nosuffix garden/data | awk '{print int($1)}')" -ge 175; grep -q garden-safe /mnt/lfcs/garden/sentinel ;;
  lvm-04) pvs --noheadings -o vg_name /dev/lfcs-disk2 | grep -qw observatory; test "$(findmnt -rn -o FSTYPE /mnt/lfcs/observatory)" = xfs ;;
  mount-01) findmnt -rn -o OPTIONS /mnt/lfcs/noexec | grep -qw noexec; findmnt -rn -o OPTIONS /mnt/lfcs/noexec | grep -qw nosuid ;;
  mount-02) findmnt -rn -o OPTIONS /mnt/lfcs/archive | grep -qw ro; fstab_uuid_entry /dev/lfcs-disk1 /mnt/lfcs/archive ext4 ro ;;
  mount-03) mount -a; findmnt -rn -o OPTIONS /mnt/lfcs/recovery | grep -qw noexec ;;
  nfs-01) exportfs -s | grep -q '^/srv/lfcs/projects  *10.10.1.0/24'; test "$(findmnt -rn --target /mnt/lfcs/projects -o SOURCE)" = 10.10.0.2:/srv/lfcs/projects; findmnt -rn --target /mnt/lfcs/projects -o FSTYPE | grep -Eq '^nfs4?$'; findmnt -rn --target /mnt/lfcs/projects -o OPTIONS | grep -qw rw; cmp /srv/lfcs/projects/README /mnt/lfcs/projects/README; fstab_source_entry 10.10.0.2:/srv/lfcs/projects /mnt/lfcs/projects nfs _netdev ;;
  sshfs-01) sudo -u student ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /srv/lfcs/keys/exam student@10.10.2.10 true; printf 'ls /srv/lfcs/node2\nquit\n' | sudo -u student sftp -q -b - -oBatchMode=yes -oIdentitiesOnly=yes -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null -i /srv/lfcs/keys/exam student@10.10.2.10; source=$(findmnt -rn --target /mnt/lfcs/remote -o SOURCE); [[ $source == student@10.10.2.10:/srv/lfcs/node2 || $source == student@node2:/srv/lfcs/node2 ]]; findmnt -rn --target /mnt/lfcs/remote -o FSTYPE | grep -qx fuse.sshfs; findmnt -rn --target /mnt/lfcs/remote -o OPTIONS | grep -qw ro; sudo -u student cmp /srv/lfcs/node2/index.html /mnt/lfcs/remote/index.html ;;
  nbd-01) systemctl is-active --quiet nbd-server; grep -q '^\[amber\]$' /etc/nbd-server/conf.d/amber.conf; test "$(findmnt -rn -o SOURCE /mnt/lfcs/amber)" = /dev/nbd0; test "$(blkid -s TYPE -o value /dev/nbd0)" = ext4; grep -qx amber-ready /mnt/lfcs/amber/sentinel ;;
  autofs-01) systemctl is-active --quiet autofs; grep -Eq '^projects +-fstype=nfs,([^ ]*,)?rw,([^ ]*,)?nobind +localhost:/srv/lfcs/projects$' /etc/auto.lfcs-projects; grep -q projects-ready /mnt/lfcs/on-demand/projects/README; test "$(findmnt -rn --target /mnt/lfcs/on-demand/projects -o SOURCE)" = localhost:/srv/lfcs/projects; findmnt -rn --target /mnt/lfcs/on-demand/projects -o FSTYPE | grep -Eq '^nfs4?$'; ! grep -q '/mnt/lfcs/on-demand' /etc/fstab ;;
  swap-01) test "$(stat -c %a /var/lib/lfcs-lab/exam.swap)" = 600; swapon --noheadings --show=NAME | grep -qx /var/lib/lfcs-lab/exam.swap ;;

  find-01) test -f /tmp/hazel-large/large-a; test "$(find /tmp/hazel-large -maxdepth 1 -type f | wc -l)" = 1 ;;
  find-02) diff -u <(find /srv/lfcs/find -type f -name '*.conf' -newermt 2026-08-20 -print | sort) /tmp/recent-configs ;;
  find-03) test -e /srv/lfcs/quarantine/exact-a; test -e /srv/lfcs/quarantine/exact-b; test ! -e /srv/lfcs/find/perm/exact-a ;;
  find-04) test ! -e /srv/lfcs/find/cache/old.tmp; test -e /srv/lfcs/find/cache/new.tmp; test -e /srv/lfcs/find/cache/foreign.tmp ;;
  find-05) ! grep -q '/archive/' /tmp/image-list; diff -u <(sort -u /tmp/image-list) /tmp/image-list ;;
  find-06) grep -q '/srv/lfcs/find/bin/helper' /tmp/suid-audit; ! grep -q '/plain$\|/data$' /tmp/suid-audit ;;
  find-07) test -f /tmp/window/inside-a; test -f /tmp/window/inside-b; test ! -e /tmp/window/after ;;
  find-08) test "$(cat /tmp/staging-count)" = "$(find /srv/lfcs/find/staging -type f | wc -l)"; ! find /srv/lfcs/find/staging -type f -empty | grep -q . ;;
  text-01|text-02|text-04|text-05|text-06|archive-01|redirection-02) test -s "/tmp/${sid/text-01/5xx-by-ip}" 2>/dev/null || case "$sid" in text-02) test -s /tmp/mobile-errors;; text-04) test -s /tmp/config-drift;; text-05) test -s /tmp/error-window;; text-06) test -s /tmp/team-names;; archive-01) test -s /tmp/common-members;; redirection-02) test -s /tmp/stream-combined;; esac ;;
  text-03) grep -Eq '^[^#]*,operator,/bin/bash$' /srv/lfcs/app/users.csv; ! grep -Eq '^[^#]*,operator,/bin/sh$' /srv/lfcs/app/users.csv ;;
  archive-02) tar -tJf /tmp/records.tar.xz >/dev/null; test -f /srv/lfcs/archives/records.tar.gz ;;
  archive-03) test -d /tmp/bundle-selected/conf.d; test ! -e /tmp/bundle-selected/logs ;;
  redirection-01) test -s /tmp/stream.out; test -s /tmp/stream.err; grep -Eq '^[0-9]+$' /tmp/stream.status ;;
  redirection-03) grep -Eq '^[0-9]+$' /tmp/stdout-count; test -s /tmp/pipeline.err; grep -Eq '^[0-9]+$' /tmp/producer.status ;;
  links-01) test "$(readlink /srv/lfcs/links/current)" = releases/v2; test -e /srv/lfcs/links/current/version ;;
  links-02) test /srv/lfcs/links/config.live -ef /srv/lfcs/links/config.backup; test "$(stat -c %h /srv/lfcs/links/config.live)" = 2 ;;
  permissions-01) test "$(stat -c %a /srv/lfcs/shared)" = 2770; test "$(stat -c %G /srv/lfcs/shared/tool.sh)" = editors ;;
  permissions-02) test "$(stat -c %U:%G:%a /srv/lfcs/bin/report-id)" = root:auditors:4750 ;;
  attributes-01) lsattr /srv/lfcs/ledger/current.log | grep -q -- '-----a'; lsattr /srv/lfcs/ledger/schema.conf | grep -q -- '----i' ;;
  git-01) test "$(cat /tmp/selected-branch)" = feature/teal; test -z "$(git -C /srv/lfcs/git/service status --porcelain)" ;;
  git-02) test -z "$(sudo -u student git -C /srv/lfcs/git/banner status --porcelain)"; test "$(sudo -u student git -C /srv/lfcs/git/banner log -1 --format=%s)" = 'integrate teal' ;;

  usermod-01) test "$(id -gn maren)" = platform; id -nG maren | grep -qw analytics; id -nG maren | grep -qw incident ;;
  usermod-02) getent passwd devin | grep -q ':/srv/home/devin:/bin/bash$'; test -f /srv/home/devin/keep.txt ;;
  usermod-03) chage -l rhea | grep -q 'Sep 20, 2026'; getent passwd rhea | grep -q ':/bin/bash$' ;;
  usermod-04) getent passwd rowan | grep -q ':/home/rowan:'; test "$(id -gn rowan)" = rowan; id -nG rowan | grep -qw authors ;;
  sudo-01) visudo -cf /etc/sudoers.d/91-lfcs-maren >/dev/null; sudo -l -U maren | grep -q '/usr/bin/systemctl restart nginx' ;;
  sudo-02) visudo -cf /etc/sudoers.d/92-lfcs-deployops >/dev/null; grep -Eq '^%deployops .*\(release\).* /usr/bin/install -m 0644 .* /srv/releases/' /etc/sudoers.d/92-lfcs-deployops; ! grep -q NOPASSWD /etc/sudoers.d/92-lfcs-deployops ;;
  sudo-03) visudo -cf /etc/sudoers.d/93-lfcs-monitor >/dev/null; grep -Eq '^Cmnd_Alias +MONITOR *= */usr/bin/journalctl, */usr/bin/systemctl status \*$' /etc/sudoers.d/93-lfcs-monitor ;;
  sudo-04) visudo -cf /etc/sudoers.d/94-lfcs-backupbot >/dev/null; sudo -l -U backupbot | grep -q '/usr/bin/rsync' ;;
  env-01) sudo -iu maren env | grep -qx LFCS_REGION=eu-west; sudo -iu maren env | grep -qx PROJECT=cedar ;;
  env-02) grep -qx 'export EDITOR=vim' /home/sampleleaf/.profile; sudo -iu sampleleaf sh -c 'test "$EDITOR" = vim' ;;
  env-03) sudo -iu devin sh -c 'test "$BUILD_ROOT" = /srv/build'; ! sudo -iu devin env | grep -q '^LOCAL_NOTE=' ;;
  limits-01) grep -Eq '^maren +soft +nofile +4096$' /etc/security/limits.d/91-lfcs.conf; ! grep -q 'ulimit.*nofile' /home/maren/.bashrc ;;
  limits-02) awk '$1=="@batch" && $2=="soft" && $3=="nproc" && $4=="64" {s++} $1=="@batch" && $2=="hard" && $3=="nproc" && $4=="96" {h++} $1=="@batch" && $2=="-" && $3=="maxlogins" && $4=="3" {m++} END{exit !(s==1&&h==1&&m==1)}' /etc/security/limits.d/92-lfcs-batch.conf ;;
  *) echo "no independent validation for $sid" >&2; exit 2 ;;
esac
