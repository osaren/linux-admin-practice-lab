#!/usr/bin/env bash
set -u -o pipefail
fail=0
check() {
  local name=$1; shift
  if "$@" >/dev/null 2>&1; then printf 'PASS\t%s\n' "$name"; else printf 'FAIL\t%s\n' "$name"; fail=$((fail+1)); fi
}
shell_check() { local name=$1 command=$2; check "$name" bash -c "$command"; }

shell_check systemd-running "test \"\$(systemctl is-system-running)\" = running"
shell_check hostname-resolves-locally "getent hosts \"\$(hostnamectl --static)\" >/dev/null && awk -v wanted=\"\$(hostnamectl --static)\" '\$1 !~ /^#/ {for(i=2;i<=NF;i++) if(\$i==wanted) found=1} END{exit !found}' /etc/hosts"
shell_check nss-baseline-sources "getent passwd root >/dev/null && getent group root >/dev/null && grep -Eq '^hosts:.*(dns|resolve)' /etc/nsswitch.conf"
shell_check namespaces-present "for n in node1 node2 node3 router1; do ip netns list | awk '{print \$1}' | grep -qx \"\$n\" || exit 1; done"
check student-sudo-host sudo -u student -H sudo -n true
for n in node1 node2 node3 router1; do check "student-sudo-$n" ip netns exec "$n" sudo -u student -H sudo -n true; done
check docker-healthy docker info
check nginx-config nginx -t
shell_check nginx-baseline-inactive "! systemctl is-active --quiet nginx"
shell_check nginx-no-owned-listeners "! ss -lntH | grep -Eq ':(8088|8089|8091|8111|8112|8113|8114|8115|8116|8443|8446)([[:space:]]|$)'"
shell_check nginx-no-scenario-sites "! find /etc/nginx/sites-enabled /etc/nginx/sites-available -maxdepth 1 \( -name 'lfcs-*' -o -name 'day1' \) -print | grep -q ."
shell_check nginx-no-broken-links "! find /etc/nginx/sites-enabled -xtype l -print | grep -q ."
check ssh-baseline-valid sshd -t
shell_check ssh-management-active "systemctl is-active --quiet ssh && systemctl is-enabled --quiet ssh"
shell_check ssh-management-port-22 "ss -lntH 'sport = :22' | grep -q . && sshd -T | grep -qx 'port 22'"
shell_check topology-connectivity "ip netns exec node1 ping -c1 -W1 10.10.2.10 >/dev/null && ip netns exec node1 ping -c1 -W1 10.10.3.10 >/dev/null && ip netns exec node1 curl -fsS --max-time 2 http://10.10.2.10:8080/ | grep -q backend=node2"
shell_check timesync-baseline "systemctl is-active --quiet systemd-timesyncd && systemctl is-enabled --quiet systemd-timesyncd && ! test -e /etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf && ! test -e /etc/systemd/timesyncd.conf.d/95-lfcs-broken.conf"
shell_check no-host-lab-firewall "! iptables -S | grep -Eq 'LFCS_(HOST|PERSIST)'"
shell_check no-lab-firewall-persistence "! test -e /etc/iptables/rules.v4 && ! test -e /etc/iptables/lfcs-router.v4"
check docker-firewall-preserved iptables -S DOCKER-USER
shell_check namespace-firewalls-clean "for n in node1 node2 node3 router1; do test \"\$(ip netns exec \"\$n\" iptables -S | wc -l)\" = 3 || exit 1; ip netns exec \"\$n\" iptables -S | grep -qx -- '-P INPUT ACCEPT' || exit 1; ip netns exec \"\$n\" iptables -S | grep -qx -- '-P OUTPUT ACCEPT' || exit 1; ip netns exec \"\$n\" iptables -S | grep -qx -- '-P FORWARD ACCEPT' || exit 1; done"
shell_check no-stale-routes "for n in node1 node2 node3; do ! ip netns exec \"\$n\" ip route show | grep -q '203.0.113.0/24' || exit 1; done"
shell_check no-scenario-mounts "! findmnt -rn -R /mnt/lfcs | grep -q ."
shell_check no-scenario-swap "! swapon --noheadings --show=NAME | grep -Eq 'lfcs|exam.swap'"
shell_check no-lab-lvm "! vgs --noheadings -o vg_name | grep -Eq 'lfcs_|lfcs$|orchard|oldfruit|freshfruit|garden|observatory'"
shell_check no-lab-pvs "for d in /dev/lfcs-disk1 /dev/lfcs-disk2 /dev/lfcs-disk3; do ! pvs --noheadings \"\$d\" 2>/dev/null | grep -q . || exit 1; done"
shell_check raw-practice-disks "for d in /dev/lfcs-disk1 /dev/lfcs-disk2 /dev/lfcs-disk3; do test \"\$(lsblk -nrpo NAME \"\$d\" | wc -l)\" = 1 || exit 1; test -z \"\$(wipefs -n \"\$d\" 2>/dev/null)\" || exit 1; done"
shell_check nbd-detached "test \"\$(blockdev --getsize64 /dev/nbd0 2>/dev/null || echo 0)\" = 0"
shell_check nbd-owned-state-clean "/usr/local/lib/lfcs/nbd-ownership.py check-clean && ! test -e /var/lib/lfcs-disks/amber.img && ! test -e /var/lib/lfcs-disks/nbd.img && ! ss -lntH 'sport = :10809' | grep -q ."
shell_check no-lab-device-mapper "! dmsetup ls 2>/dev/null | grep -Eq 'lfcs|orchard|oldfruit|freshfruit|garden|observatory'"
shell_check no-lab-containers "! docker ps -a --format '{{.Names}}' | grep -Eq '^(web-basil|web-mint|web-fern|web-ivy)$'"
shell_check no-libvirt-fixtures "! test -e /srv/lfcs/virt && ! test -e /tmp/virt-list && ! test -e /tmp/virt-dominfo && ! test -e /tmp/exam-maple-info"
shell_check no-scenario-schedules "! find /etc/cron.d -maxdepth 1 \( -name 'alder-backup' -o -name 'maple-prune' -o -name 'lfcs-inventory' \) -print | grep -q . && ! atq | grep -q ."
shell_check no-scenario-users "for u in scout dana contractor reviewer1 maren devin rhea tempwriter rowan sampleleaf backupbot release archive buildbot deployer hazel; do ! getent passwd \"\$u\" >/dev/null || exit 1; done"
shell_check sudo-baseline "visudo -cf /etc/sudoers >/dev/null && test \"\$(stat -c %a /etc/sudoers.d/00-lfcs-student-admin)\" = 440 && grep -qx 'student ALL=(ALL) NOPASSWD: ALL' /etc/sudoers.d/00-lfcs-student-admin && ! find /etc/sudoers.d -maxdepth 1 -name '9*-lfcs-*' -print | grep -q ."
shell_check no-fstab-markers "! grep -Eq 'LFCS-(LAB|EXT)|/mnt/lfcs|exam.swap' /etc/fstab"
shell_check no-export-leaks "! grep -RqsE '/srv/lfcs/(share|projects)' /etc/exports /etc/exports.d"
shell_check no-autofs-leaks "! test -e /etc/auto.master.d/lfcs.autofs && ! test -e /etc/auto.master.d/lfcs-ext.autofs && ! test -e /etc/auto.lfcs && ! test -e /etc/auto.lfcs-projects && ! test -e /etc/auto.share && ! grep -RqsE '/srv/lfcs/(share|projects)' /etc/auto.master /etc/auto.master.d /etc/auto.* && ! systemctl is-active --quiet autofs"
shell_check no-owned-pids "! find /run/lfcs-lab -maxdepth 1 -name '*.pid' -print | grep -vE '/(node2-http|node3-http)\.pid$' | grep -q ."
shell_check no-failed-units "! systemctl --failed --no-legend | grep -q ."
shell_check no-lab-netplan "! find /etc/netplan -maxdepth 1 -name '9[01]-lfcs-*.yaml' -print | grep -q ."
shell_check no-lab-networkmanager "! nmcli -t -f NAME connection show | grep -Eq '^lfcs-(dummy|cedar|aspen|maple|maple-old)$' && ! ip -o link show | grep -Eq 'nm(cedar|aspen|maple)0'"

printf 'TOTAL=%d PASS=%d FAIL=%d\n' 45 "$((45-fail))" "$fail"
exit "$fail"
