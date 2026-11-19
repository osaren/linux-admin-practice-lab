#!/usr/bin/env bash
set -euo pipefail

# QA-only known-good final states. This file is installed only by the regression
# runner and is deliberately separate from student-facing tasks and solutions.
sid=${1:?scenario id required}

if /usr/local/lib/lfcs/guest-regression-solutions.sh "$sid" >/dev/null 2>&1; then
  exit 0
fi

case "$sid" in
  sysinfo-02) { hostnamectl --static; timedatectl show -p Timezone --value; cat /proc/sys/kernel/random/boot_id; } >/tmp/boot-clock-report ;;
  systemd-04) sed -i 's/User=missing-alder/User=svc-alder/' /etc/systemd/system/alder-worker.service; systemctl daemon-reload; systemctl enable --now alder-worker ;;
  systemd-05) mkdir -p /etc/systemd/system/pine-api.service.d; printf '[Service]\nEnvironment=APP_MODE=production\n' >/etc/systemd/system/pine-api.service.d/override.conf; systemctl daemon-reload; systemctl restart pine-api ;;
  systemd-06) systemctl unmask juniper-agent; sed -i 's/Restart=no/Restart=on-failure/' /etc/systemd/system/juniper-agent.service; systemctl daemon-reload; systemctl enable --now juniper-agent ;;
  systemd-07) mkdir -p /etc/systemd/system/spruce-web.service.d; printf '[Unit]\nRequires=spruce-data.service\nAfter=spruce-data.service\n' >/etc/systemd/system/spruce-web.service.d/override.conf; systemctl daemon-reload; systemctl enable --now spruce-data spruce-web ;;
  systemd-08) sed -i 's|EnvironmentFile=.*|EnvironmentFile=/etc/lfcs-lab/hemlock.env|;s/Restart=no/Restart=on-failure/' /etc/systemd/system/hemlock-job.service; systemctl daemon-reload; systemctl enable --now hemlock-job ;;
  cron-03) printf '40 2 1 * * root /usr/local/bin/maple-prune\n' >/etc/cron.d/maple-prune; chmod 0644 /etc/cron.d/maple-prune ;;
  cron-04) sed -i '/cedar-index/d' /etc/anacrontab; printf '7 12 cedar-index /usr/local/bin/cedar-index\n' >>/etc/anacrontab ;;
  process-02) p=$(cat /run/lfcs-lab/extended-walnut.pid); printf '%s\n/usr/bin/sleep\n/srv/lfcs/process/walnut.data\n' "$p" >/tmp/walnut-report; renice 12 -p "$p" >/dev/null ;;
  docker-01) { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' web-fern; printf '/srv/lfcs/fern\n8131\npractice\n'; } >/tmp/web-fern-report ;;
  timesync-01) printf '[Time]\nNTP=time.cloudflare.com\nFallbackNTP=ntp.ubuntu.com\nPollIntervalMinSec=32\nPollIntervalMaxSec=1024\n' >/etc/systemd/timesyncd.conf.d/95-lfcs-broken.conf; systemctl enable --now systemd-timesyncd ;;
  timesync-02) printf '[Time]\nNTP=1.1.1.1\nConnectionRetrySec=30\n' >/etc/systemd/timesyncd.conf.d/95-lfcs-broken.conf; systemctl enable --now systemd-timesyncd ;;
  virt-01) { printf 'ACTIVE\n'; virsh -c test:///default list; printf 'ALL\n'; virsh -c test:///default list --all; } >/tmp/virt-list ;;
  virt-02) virsh -c test:///default dominfo test | awk -F: '/^Name:/{gsub(/^ +/,"",$2); print $2} /^State:/{gsub(/^ +/,"",$2); print $2} /^Max memory:/{gsub(/^ +/,"",$2); print int($2/1024)} /^CPU.s.:/{gsub(/^ +/,"",$2); print $2}' >/tmp/virt-dominfo ;;
  virt-03) cat >/srv/lfcs/virt/lifecycle.sh <<'EOF'
#!/bin/bash
virsh -c test:///default start exam-elm
virsh -c test:///default shutdown exam-elm
virsh -c test:///default destroy exam-elm
virsh -c test:///default autostart exam-elm
virsh -c test:///default undefine exam-elm
EOF
    chmod 0755 /srv/lfcs/virt/lifecycle.sh ;;
  virt-04) cat >/srv/lfcs/virt/exam-ash.xml <<'EOF'
<domain type='test'><name>exam-ash</name><memory unit='MiB'>768</memory><vcpu>2</vcpu><devices><disk type='file'><source file='/srv/lfcs/virt/exam-ash.qcow2'/><target dev='vda' bus='virtio'/></disk><interface type='network'><source network='default'/></interface></devices></domain>
EOF
    ;;
  virt-05) sed -i "s|<memory unit='MiB'>512</memory>|<memory unit='MiB'>1024</memory>|;s|<vcpu>1</vcpu>|<vcpu>3</vcpu>|;s|<autostart>disabled</autostart>|<autostart>enabled</autostart>|" /srv/lfcs/virt/exam-oak.xml ;;
  virt-06) qemu-img info --output=json /srv/lfcs/virt/exam-maple.qcow2 >/tmp/exam-maple-info ;;
  virt-07) qemu-img resize /srv/lfcs/virt/exam-willow.qcow2 112M >/dev/null ;;
  virt-09) cat >/srv/lfcs/virt/create-cedar.sh <<'EOF'
#!/bin/bash
virt-install --name exam-cedar --memory 512 --vcpus 1 --import --disk path=/srv/lfcs/virt/exam-cedar.qcow2,bus=virtio --network network=default --graphics none --noautoconsole --print-xml
EOF
    chmod 0755 /srv/lfcs/virt/create-cedar.sh ;;

  iptables-01) ip netns exec node2 iptables -I INPUT 1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; ip netns exec node2 iptables -A INPUT -p tcp --dport 9121 -j DROP ;;
  iptables-02) ip netns exec node2 iptables -I INPUT 1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; ip netns exec node2 iptables -I INPUT 2 -s 10.10.1.0/24 -p tcp --dport 9122 -j ACCEPT; ip netns exec node2 iptables -A INPUT -p tcp --dport 9122 -j REJECT ;;
  iptables-03) ip netns exec node1 iptables -A OUTPUT -d 10.10.3.10 -p tcp --dport 9123 -j REJECT ;;
  iptables-04) ip netns exec node2 iptables -t nat -A OUTPUT -p tcp -d 127.0.0.1 --dport 8184 -j REDIRECT --to-ports 8084 ;;
  iptables-05) ip netns exec router1 sysctl -q -w net.ipv4.ip_forward=1; ip netns exec router1 iptables -t nat -A PREROUTING -p tcp --dport 8185 -j DNAT --to-destination 10.10.2.10:8080; ip netns exec router1 iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; ip netns exec router1 iptables -A FORWARD -p tcp -d 10.10.2.10 --dport 8080 -j ACCEPT ;;
  iptables-06) ip netns exec router1 sysctl -q -w net.ipv4.ip_forward=1; ip netns exec router1 iptables -t nat -A POSTROUTING -s 10.10.1.0/24 -o eth0 -j MASQUERADE ;;
  iptables-07) ip netns exec router1 sysctl -q -w net.ipv4.ip_forward=1; ip netns exec router1 iptables -I FORWARD 1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; ip netns exec router1 iptables -I FORWARD 2 -s 10.10.1.0/24 -d 10.10.3.10 -p tcp --dport 9127 -j ACCEPT ;;
  iptables-08) ip netns exec node2 iptables -I INPUT 1 -s 10.10.1.0/24 -p tcp --dport 9128 -j ACCEPT ;;
  iptables-09) iptables -I LFCS_PERSIST 1 -s 10.10.1.0/24 -p tcp --dport 8139 -j ACCEPT; iptables-save >/etc/iptables/rules.v4 ;;
  nginx-01) printf 'server { listen 8111; location / { return 200 "amber-ready\\n"; } }\n' >/etc/nginx/sites-available/lfcs-ext-amber; ln -sf /etc/nginx/sites-available/lfcs-ext-amber /etc/nginx/sites-enabled/lfcs-ext-amber; nginx -t; systemctl enable --now nginx; systemctl reload nginx ;;
  nginx-02) printf 'server { listen 8112; root /srv/lfcs/alder; location / { index index.html; try_files $uri $uri/ =404; } }\n' >/etc/nginx/sites-available/lfcs-ext-alder; ln -sf /etc/nginx/sites-available/lfcs-ext-alder /etc/nginx/sites-enabled/lfcs-ext-alder; nginx -t; systemctl reload nginx ;;
  nginx-04) printf 'server { listen 8114; location /api/ { proxy_pass http://10.10.2.10:8080/; } location / { return 404; } }\n' >/etc/nginx/sites-available/lfcs-ext-api; ln -sf /etc/nginx/sites-available/lfcs-ext-api /etc/nginx/sites-enabled/lfcs-ext-api; nginx -t; systemctl reload nginx ;;
  nginx-05) printf 'server { listen 8115; listen 8116; location / { return 200 "twin-ready\\n"; } }\n' >/etc/nginx/sites-available/lfcs-ext-twin; ln -sf /etc/nginx/sites-available/lfcs-ext-twin /etc/nginx/sites-enabled/lfcs-ext-twin; nginx -t; systemctl reload nginx ;;
  nginx-06) sed -i 's|missing.key|server.key|' /etc/nginx/sites-available/lfcs-ext-fern; chmod 0600 /etc/lfcs/tls/fern/server.key; ln -sf /etc/nginx/sites-available/lfcs-ext-fern /etc/nginx/sites-enabled/lfcs-ext-fern; nginx -t; systemctl reload nginx ;;
  ssh-match-02) sed -i '/Match Group sftp-only/,$s/X11Forwarding yes/X11Forwarding no/' /etc/lfcs-lab/sshd-match.conf; cat >>/etc/lfcs-lab/sshd-match.conf <<'EOF'
    ForceCommand internal-sftp
EOF
    ;;
  ssh-match-03) sed -i 's/^PermitRootLogin yes/PermitRootLogin no/;s|Banner /etc/missing-banner|Banner /etc/issue.net|' /etc/lfcs-lab/sshd-match.conf; printf '/etc/issue.net\n' >/tmp/deployer-banner ;;

  lvm-01) pvmove /dev/lfcs-disk2 >/dev/null; vgreduce orchard /dev/lfcs-disk2 >/dev/null ;;
  lvm-02) vgreduce oldfruit /dev/lfcs-disk2 >/dev/null; vgcreate freshfruit /dev/lfcs-disk2 >/dev/null; lvcreate -L 96M -n crates freshfruit >/dev/null; mkfs.ext4 -F /dev/freshfruit/crates >/dev/null; mkdir -p /mnt/lfcs/crates; mount /dev/freshfruit/crates /mnt/lfcs/crates ;;
  lvm-04) pvcreate -ff -y /dev/lfcs-disk2 >/dev/null; vgextend observatory /dev/lfcs-disk2 >/dev/null; lvextend -L +96M /dev/observatory/logs >/dev/null; xfs_growfs /mnt/lfcs/observatory >/dev/null ;;
  mount-01) mount -o remount,noexec,nosuid /mnt/lfcs/noexec; u=$(blkid -s UUID -o value /dev/lfcs-disk1); printf 'UUID=%s /mnt/lfcs/noexec ext4 defaults,noexec,nosuid 0 2 # LFCS-EXT\n' "$u" >>/etc/fstab ;;
  mount-02) mount -o remount,ro /mnt/lfcs/archive; u=$(blkid -s UUID -o value /dev/lfcs-disk1); printf 'UUID=%s /mnt/lfcs/archive ext4 defaults,ro 0 2 # LFCS-EXT\n' "$u" >>/etc/fstab ;;
  nfs-01) mkdir -p /etc/exports.d; printf '/srv/lfcs/projects 10.10.1.0/24(rw,sync,no_subtree_check,insecure)\n' >/etc/exports.d/lfcs-ext-projects.exports; exportfs -ra; nsenter --net=/var/run/netns/node1 mount -t nfs -o _netdev 10.10.0.2:/srv/lfcs/projects /mnt/lfcs/projects; printf '10.10.0.2:/srv/lfcs/projects /mnt/lfcs/projects nfs defaults,_netdev 0 0 # LFCS-EXT\n' >>/etc/fstab ;;
  nbd-01) systemctl start nbd-server; for i in {1..100}; do ss -lntH 'sport = :10809' | grep -q . && break; sleep 0.02; done; nbd-client -l 127.0.0.1 | grep -qx amber; nbd-client -N amber 127.0.0.1 10809 /dev/nbd0 >/dev/null; mkfs.ext4 -F /dev/nbd0 >/dev/null; mount /dev/nbd0 /mnt/lfcs/amber; printf 'amber-ready\n' >/mnt/lfcs/amber/sentinel ;;
  autofs-01) printf '/mnt/lfcs/on-demand /etc/auto.lfcs-projects\n' >/etc/auto.master.d/lfcs-ext.autofs; printf 'projects -fstype=nfs,rw,nobind localhost:/srv/lfcs/projects\n' >/etc/auto.lfcs-projects; systemctl enable --now autofs; systemctl restart autofs; for i in {1..20}; do ls /mnt/lfcs/on-demand/projects >/dev/null 2>&1 && break; sleep 0.1; done; ls /mnt/lfcs/on-demand/projects >/dev/null ;;
  swap-01) fallocate -l 64M /var/lib/lfcs-lab/exam.swap; chmod 0600 /var/lib/lfcs-lab/exam.swap; mkswap /var/lib/lfcs-lab/exam.swap >/dev/null; swapon /var/lib/lfcs-lab/exam.swap; printf '/var/lib/lfcs-lab/exam.swap none swap sw 0 0 # LFCS-EXT\n' >>/etc/fstab ;;

  find-01) mkdir -p /tmp/hazel-large; find /srv/lfcs/find/owner -type f -user hazel -size +10k -exec cp -p {} /tmp/hazel-large/ \; ;;
  find-03) mkdir -p /srv/lfcs/quarantine; find /srv/lfcs/find/perm -type f -perm 0640 -exec mv {} /srv/lfcs/quarantine/ \; ;;
  find-04) find /srv/lfcs/find/cache -type f -group cacheops -name '*.tmp' -mmin +60 -delete ;;
  find-05) find /srv/lfcs/find/media/live -type f \( -iname '*.jpg' -o -iname '*.png' \) | sort >/tmp/image-list ;;
  find-06) find /srv/lfcs/find/bin -type f -perm -4000 -executable -printf '%D %i %m %u %p\n' >/tmp/suid-audit ;;
  find-07) mkdir -p /tmp/window; find /srv/lfcs/find/inbox -type f -newer /srv/lfcs/markers/start ! -newer /srv/lfcs/markers/end -exec cp -p {} /tmp/window/ \; ;;
  find-08) find /srv/lfcs/find/staging -type f -empty -delete; find /srv/lfcs/find/staging -type f | wc -l >/tmp/staging-count ;;
  text-01) awk '$4 ~ /^5/ {c[$1]++} END {for(i in c) print c[i],i}' /var/log/lfcs/access.log | sort -k1,1nr -k2,2 >/tmp/5xx-by-ip ;;
  text-03) awk -F, 'BEGIN{OFS=","} /^#/ {print;next} $2=="operator"&&$3=="/bin/sh"{$3="/bin/bash"} {print}' /srv/lfcs/app/users.csv >/tmp/users.csv; mv /tmp/users.csv /srv/lfcs/app/users.csv ;;
  text-04) awk -F= 'FNR==NR {if($0 !~ /^#/ && NF>1)e[$1]=$2; next} $0 !~ /^#/ && NF>1 {seen[$1]=1; if(!($1 in e)||e[$1]!=$2)print $1} END{for(k in e)if(!(k in seen))print k}' /srv/lfcs/app/expected.conf /srv/lfcs/app/actual.conf | sort -u >/tmp/config-drift ;;
  text-05) awk '$1>="10:15:00" && $1<="10:45:59" && $2=="ERROR" {$1=$2=""; sub(/^  */,""); print}' /var/log/lfcs/service.log >/tmp/error-window ;;
  text-06) sed 's/^[[:space:]]*//;s/[[:space:]]*$//' /srv/lfcs/app/teams.txt | grep -v '^#' | grep -v '^$' | tr '[:upper:]' '[:lower:]' | sort -u >/tmp/team-names ;;
  archive-01) comm -12 <(tar -tzf /srv/lfcs/archives/one.tar.gz | grep -v '/$' | sort) <(tar -tJf /srv/lfcs/archives/two.tar.xz | grep -v '/$' | sort) >/tmp/common-members ;;
  archive-03) mkdir -p /tmp/bundle-selected; tar -xjf /srv/lfcs/archives/bundle.tar.bz2 -C /tmp/bundle-selected conf.d ;;
  redirection-01) set +e; /usr/local/bin/lfcs-streams >/tmp/stream.out 2>/tmp/stream.err; rc=$?; set -e; printf '%s\n' "$rc" >/tmp/stream.status ;;
  redirection-02) for i in 1 2; do /usr/local/bin/lfcs-streams >>/tmp/stream-combined 2>&1 || true; done ;;
  redirection-03) set +e; set -o pipefail; /usr/local/bin/lfcs-streams 2>/tmp/pipeline.err | wc -l >/tmp/stdout-count; rc=${PIPESTATUS[0]}; set -e; printf '%s\n' "$rc" >/tmp/producer.status ;;
  links-01) rm -f /srv/lfcs/links/current; ln -s releases/v2 /srv/lfcs/links/current ;;
  links-02) ln /srv/lfcs/links/config.live /srv/lfcs/links/config.backup ;;
  permissions-01) chgrp editors /srv/lfcs/shared /srv/lfcs/shared/tool.sh; chmod 2770 /srv/lfcs/shared; chmod 0750 /srv/lfcs/shared/tool.sh ;;
  permissions-02) chown root:auditors /srv/lfcs/bin/report-id; chmod 4750 /srv/lfcs/bin/report-id ;;
  attributes-01) chattr +a /srv/lfcs/ledger/current.log; chattr +i /srv/lfcs/ledger/schema.conf; lsattr /srv/lfcs/ledger/current.log /srv/lfcs/ledger/schema.conf >/tmp/ledger-attributes ;;
  git-01) for b in feature/amber feature/teal feature/violet; do if git -c safe.directory=/srv/lfcs/git/service -C /srv/lfcs/git/service show "$b:app.conf" | grep -qx FEATURE_GATE=true && git -c safe.directory=/srv/lfcs/git/service -C /srv/lfcs/git/service show "$b:app.conf" | grep -qx API_LEVEL=7; then printf '%s\n' "$b"; fi; done >/tmp/selected-branch ;;

  usermod-01) usermod -g platform -aG analytics,incident -s /bin/bash maren ;;
  usermod-02) mkdir -p /srv/home; usermod -d /srv/home/devin -m -s /bin/bash devin ;;
  usermod-03) chage -E 2026-09-20 -M 21 -m 2 -W 5 rhea; usermod -p "$(openssl passwd -6 -salt lfcs practice)" rhea ;;
  usermod-04) usermod -l rowan -d /home/rowan -m tempwriter; groupmod -n rowan tempwriter ;;
  sudo-02) printf '%%deployops ALL=(release) /usr/bin/install -m 0644 * /srv/releases/\n' >/etc/sudoers.d/92-lfcs-deployops; chmod 0440 /etc/sudoers.d/92-lfcs-deployops ;;
  sudo-03) printf 'Cmnd_Alias MONITOR = /usr/bin/journalctl, /usr/bin/systemctl status *\n%%monitoring ALL=(root) NOPASSWD: MONITOR\n' >/etc/sudoers.d/93-lfcs-monitor; chmod 0440 /etc/sudoers.d/93-lfcs-monitor ;;
  sudo-04) printf 'backupbot ALL=(archive) NOPASSWD: /usr/bin/rsync *\n' >/etc/sudoers.d/94-lfcs-backupbot; chmod 0440 /etc/sudoers.d/94-lfcs-backupbot ;;
  env-01) printf 'export LFCS_REGION=eu-west\n' >/etc/profile.d/lfcs-ext-region.sh; printf 'export PROJECT=cedar\n' >>/home/maren/.profile ;;
  env-02) printf '\nexport EDITOR=vim\numask 027\n' >>/etc/skel/.profile; useradd -m sampleleaf ;;
  env-03) sed -i '/BUILD_ROOT=/d;/LOCAL_NOTE=/d' /home/devin/.profile; printf 'export BUILD_ROOT=/srv/build\nLOCAL_NOTE=private\n' >>/home/devin/.profile ;;
  limits-01) sed -i '/ulimit .*nofile/d' /home/maren/.bashrc; printf 'maren soft nofile 4096\nmaren hard nofile 8192\n' >/etc/security/limits.d/91-lfcs.conf ;;

  commands-01) find /srv/lfcs/search -type f -user scout -size +8k -print | sort >/tmp/lfcs-report ;;
  commands-02) grep '^ERROR' /var/log/lfcs-app.log >/tmp/lfcs-errors; tar -cJf /tmp/lfcs-logs.tar.xz -C /tmp lfcs-errors -C /srv/lfcs config ;;
  operations-02) cat >/usr/local/bin/report-writer <<'EOF'
#!/bin/sh
echo ready >/var/log/report-writer.log
exec sleep infinity
EOF
    chmod 0755 /usr/local/bin/report-writer; cat >/etc/systemd/system/report-writer.service <<'EOF'
[Unit]
Description=Report writer
[Service]
ExecStart=/usr/local/bin/report-writer
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload; systemctl enable --now report-writer ;;
  operations-03) systemctl daemon-reload; systemctl restart cedar-worker ;;
  operations-04) kill "$(cat /run/lfcs-lab/runaway.pid)" 2>/dev/null || true; renice 10 -p "$(cat /run/lfcs-lab/birch.pid)" >/dev/null ;;
  operations-05) printf '*/5 * * * * root /usr/local/bin/lfcs-inventory\n' >/etc/cron.d/lfcs-inventory; chmod 0644 /etc/cron.d/lfcs-inventory ;;
  operations-06) echo /usr/local/bin/lfcs-once | sudo -u student at -M now + 10 minutes >/dev/null 2>&1 ;;
  operations-08) printf 'server { listen 8091; location / { return 200 "day1-ready\\n"; } }\n' >/etc/nginx/sites-available/day1; ln -sf /etc/nginx/sites-available/day1 /etc/nginx/sites-enabled/day1; nginx -t; systemctl enable --now nginx; systemctl reload nginx ;;
  day1-mini) cat >/etc/systemd/system/lfcs-sleeper.service <<'EOF'
[Unit]
Description=LFCS sleeper
[Service]
ExecStart=/usr/bin/sleep infinity
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload; systemctl enable --now lfcs-sleeper; sysctl -q -w vm.swappiness=20; printf 'vm.swappiness = 20\n' >/etc/sysctl.d/90-lfcs-swappiness.conf; find /srv/lfcs/search -type f -size +8k >/tmp/day1-files; echo /usr/local/bin/lfcs-once | sudo -u student at -M now + 10 minutes >/dev/null 2>&1 ;;

  networking-01) ip netns exec node1 ip addr flush dev eth0 scope global; ip netns exec node1 ip addr add 10.10.1.10/24 dev eth0; ip netns exec node1 ip route replace default via 10.10.1.1 ;;
  networking-03) ip netns exec node3 ip route replace default via 10.10.3.1 ;;
  networking-04) ip netns exec node1 ip -6 addr add fd10:10:1::10/64 dev eth0; ip netns exec node1 ip -6 route add default via fd10:10:1::1 ;;
  networking-05) nmcli con add type dummy ifname lfcs-dummy0 con-name lfcs-dummy ipv4.method manual ipv4.addresses 192.0.2.10/24 ipv4.never-default yes ipv6.method disabled; nmcli con up lfcs-dummy >/dev/null ;;
  networking-06) cat >/etc/netplan/91-lfcs-dummy.yaml <<'EOF'
network:
  version: 2
  ethernets:
    npdummy0:
      match:
        name: npdummy0
      addresses: [198.51.100.20/24]
EOF
    netplan generate ;;
  networking-08) chmod 0700 /home/student/.ssh; chmod 0600 /home/student/.ssh/authorized_keys; sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/lfcs-lab/sshd-node2.conf; old=$(cat /run/lfcs-lab/sshd-node2.pid); kill "$old" 2>/dev/null || true; for _ in {1..100}; do ip netns exec node2 ss -lntH 'sport = :22' | grep -q . || break; sleep 0.02; done; ! ip netns exec node2 ss -lntH 'sport = :22' | grep -q .; ip netns exec node2 /usr/sbin/sshd -D -e -f /etc/lfcs-lab/sshd-node2.conf >/run/lfcs-lab/sshd-node2.log 2>&1 & echo $! >/run/lfcs-lab/sshd-node2.pid; for _ in {1..100}; do ip netns exec node2 ss -lntH 'sport = :22' | grep -q . && break; sleep 0.02; done; ip netns exec node2 ss -lntH 'sport = :22' | grep -q . ;;
  networking-09) sed -i '/InvalidDirective/d;s/^Port .*/Port 2223/' /etc/lfcs-lab/sshd-node3.conf; printf 'AllowGroups remoteops\n' >>/etc/lfcs-lab/sshd-node3.conf; ip netns exec node3 /usr/sbin/sshd -D -e -f /etc/lfcs-lab/sshd-node3.conf >/run/lfcs-lab/sshd-node3.log 2>&1 & echo $! >/run/lfcs-lab/sshd-node3.pid; for _ in {1..100}; do ip netns exec node3 ss -lntH 'sport = :2223' | grep -q . && break; sleep 0.02; done; ip netns exec node3 ss -lntH 'sport = :2223' | grep -q . ;;
  networking-10) printf '[Time]\nNTP=time.cloudflare.com\n' >/etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf; systemctl reset-failed systemd-timesyncd; systemctl enable systemd-timesyncd; systemctl restart systemd-timesyncd ;;
  networking-11) old=$(cat /run/lfcs-lab/node2-http.pid); kill "$old" 2>/dev/null || true; for _ in {1..200}; do ip netns exec node2 ss -lntH 'sport = :8083' | grep -q . || break; sleep 0.05; done; ! ip netns exec node2 ss -lntH 'sport = :8083' | grep -q .; ip netns exec node2 python3 -m http.server 8084 --bind 0.0.0.0 --directory /srv/lfcs/node2 >/run/lfcs-lab/node2-http.log 2>&1 & echo $! >/run/lfcs-lab/node2-http.pid; for _ in {1..200}; do ip netns exec node2 curl --max-time 1 -fsS http://127.0.0.1:8084/ >/dev/null 2>&1 && break; sleep 0.05; done; ip netns exec node2 curl --max-time 1 -fsS http://127.0.0.1:8084/ >/dev/null ;;
  networking-12) ip netns exec node1 ip route replace 203.0.113.0/24 via 10.10.1.1; cat >/etc/netplan/90-lfcs-node1.yaml <<'EOF'
network:
  version: 2
  ethernets:
    lfcs-node1:
      match: {name: node1-placeholder}
      routes:
        - {to: 203.0.113.0/24, via: 10.10.1.1}
EOF
    ;;
  nmcli-01) nmcli con modify lfcs-cedar ipv4.addresses 198.51.100.20/24 ipv4.never-default yes; nmcli con up lfcs-cedar >/dev/null ;;
  nmcli-02) nmcli con modify lfcs-aspen +ipv4.routes "198.51.100.0/24 192.0.2.1"; nmcli con up lfcs-aspen >/dev/null ;;
  nmcli-03) nmcli con modify lfcs-maple-old connection.autoconnect no; nmcli con modify lfcs-maple connection.autoconnect yes ipv4.never-default yes; nmcli con up lfcs-maple >/dev/null ;;
  day2-mini) ip netns exec node1 ip addr replace 10.10.1.10/24 dev eth0; sed -i '/api.internal/d' /etc/netns/node1/hosts; printf '10.10.2.10 api.internal\n' >>/etc/netns/node1/hosts; ip netns exec node1 ip route replace 203.0.113.0/24 via 10.10.1.1; printf 'network:\n  version: 2\n  ethernets:\n    node1-placeholder:\n      routes:\n        - {to: 203.0.113.0/24, via: 10.10.1.1}\n' >/etc/netplan/90-lfcs-node1.yaml; printf '[Time]\nNTP=time.cloudflare.com\n' >/etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf ;;

  advanced-01) ip netns exec router1 iptables -F FORWARD; ip netns exec router1 iptables -P FORWARD DROP; ip netns exec router1 iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; ip netns exec router1 iptables -A FORWARD -s 10.10.1.0/24 -d 10.10.2.10 -p tcp --dport 8080 -j ACCEPT ;;
  advanced-02) iptables -F LFCS_HOST; iptables -A LFCS_HOST -s 10.10.1.0/24 -p tcp --dport 8092 -j ACCEPT; iptables -A LFCS_HOST -p tcp --dport 8092 -j REJECT ;;
  advanced-03) ip netns exec router1 sysctl -q -w net.ipv4.ip_forward=1; ip netns exec router1 iptables -t nat -A POSTROUTING -s 10.10.1.0/24 -o eth0 -j MASQUERADE ;;
  advanced-04) ip netns exec router1 sysctl -q -w net.ipv4.ip_forward=1; ip netns exec router1 iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; ip netns exec router1 iptables -A FORWARD -p tcp -d 10.10.2.10 --dport 8080 -j ACCEPT ;;
  advanced-05) ip addr add 172.20.0.1/24 dev br-lfcs; ip link set br-lfcs up; ip link set br-port2 master br-lfcs; ip link set br-port1 up; ip link set br-port2 up ;;
  advanced-06) ip link set lfcs-bond-a nomaster; ip link set lfcs-bond0 down; ip link set lfcs-bond0 type bond mode active-backup; ip link set lfcs-bond-a master lfcs-bond0; ip link set lfcs-bond-b master lfcs-bond0; ip addr flush dev lfcs-bond-a; ip addr add 172.21.0.10/24 dev lfcs-bond0; ip link set lfcs-bond0 up; ip link set lfcs-bond-a up; ip link set lfcs-bond-b up ;;
  advanced-07) sed -i 's/10.10.2.10:8088/10.10.2.10:8080/' /etc/nginx/sites-available/lfcs-proxy; nginx -t; systemctl reload nginx ;;
  advanced-10) chmod 0600 /srv/lfcs/keys/exam; sudo -u student sshfs -o IdentityFile=/srv/lfcs/keys/exam,StrictHostKeyChecking=no,UserKnownHostsFile=/dev/null student@10.10.2.10:/srv/lfcs/node2 /mnt/lfcs/sshfs ;;
  advanced-11) printf '/mnt/lfcs/auto /etc/auto.lfcs\n' >/etc/auto.master.d/lfcs.autofs; printf 'share -fstype=nfs,rw localhost:/srv/lfcs/share\n' >/etc/auto.lfcs; systemctl enable --now autofs; systemctl restart autofs; ls /mnt/lfcs/auto/share >/dev/null ;;
  advanced-12) nbd-client -l localhost | grep -qx lfcs-disk; nbd-client -N lfcs-disk localhost /dev/nbd0 >/dev/null; test "$(blkid -s TYPE -o value /dev/nbd0)" = ext4; mount /dev/nbd0 /mnt/lfcs/nbd ;;

  opsusers-01) usermod -aG deploy dana ;;
  opsusers-02) useradd -m -u 1777 -g projects -s /bin/bash -e 2026-09-15 contractor; chage -M 14 contractor ;;
  opsusers-03) setfacl -m g:reviewers:rwX,d:g:reviewers:rwX /srv/lfcs/review; setfacl -m g:reviewers:rw /srv/lfcs/review/existing ;;
  opsusers-04) printf 'student soft nofile 4096\nstudent hard nofile 8192\n' >/etc/security/limits.d/90-lfcs.conf ;;
  opsusers-05) printf 'export LFCS_REGION=eu-west\n' >/etc/profile.d/lfcs-region.sh; printf 'export TEAM=operations\n' >>/home/student/.profile ;;
  opsusers-06) docker rm -f web-basil >/dev/null; docker run -d --name web-basil -p 8086:80 -v /srv/lfcs/container:/usr/share/nginx/html:ro nginx:alpine >/dev/null ;;
  opsusers-07) docker rm -f web-mint >/dev/null; docker run -d --name web-mint -v /srv/lfcs/mint:/data:ro nginx:alpine >/dev/null ;;
  opsusers-08) rm -f /etc/apt/sources.list.d/lfcs-broken.list; apt-get update >/dev/null; dpkg-query -S /bin/ip | head -1 >/tmp/package-owner ;;
  opsusers-09) sestatus 2>/dev/null | awk -F: '/SELinux status/{gsub(/^ +/,"",$2); print toupper(substr($2,1,1)) substr($2,2)}' >/tmp/selinux-mode || true; test -s /tmp/selinux-mode || printf 'Disabled\n' >/tmp/selinux-mode; printf 'UNSUPPORTED\n' >/tmp/selinux-fcontext ;;
  opsusers-10) cp /var/lib/lfcs-lab/nsswitch.clean /etc/nsswitch.conf ;;
  opsusers-11) systemctl enable --now mint-agent ;;
  opsusers-12) { printf 'lfcs-guest\n512\ndisabled\n'; } >/tmp/virsh-report ;;
  day4-mini) usermod -aG deploy dana; setfacl -m g:reviewers:rwX,d:g:reviewers:rwX /srv/lfcs/review; systemctl enable --now mint-agent; printf 'student soft nofile 4096\nstudent hard nofile 8192\n' >/etc/security/limits.d/90-lfcs.conf ;;

  storage-01) parted -s /dev/lfcs-disk1 mklabel gpt mkpart primary ext4 1MiB 201MiB; partprobe /dev/lfcs-disk1; udevadm settle; p=$(lsblk -nrpo NAME /dev/lfcs-disk1 | sed -n '2p'); test -b "$p"; mkfs.ext4 -F -L LFCS_DATA "$p" >/dev/null; mkdir -p /mnt/lfcs/data; mount "$p" /mnt/lfcs/data ;;
  storage-02) mkfs.xfs -f -L LFCS_XFS /dev/lfcs-disk2 >/dev/null; mkdir -p /mnt/lfcs/xfs; mount /dev/lfcs-disk2 /mnt/lfcs/xfs; u=$(blkid -s UUID -o value /dev/lfcs-disk2); printf 'UUID=%s /mnt/lfcs/xfs xfs defaults 0 2 # LFCS-LAB\n' "$u" >>/etc/fstab ;;
  storage-03) pvcreate -ff -y /dev/lfcs-disk1 >/dev/null; vgcreate lfcs_vg /dev/lfcs-disk1 >/dev/null; lvcreate -L 160M -n data lfcs_vg >/dev/null; mkfs.ext4 -F /dev/lfcs_vg/data >/dev/null; mkdir -p /mnt/lfcs/lvm; mount /dev/lfcs_vg/data /mnt/lfcs/lvm; u=$(blkid -s UUID -o value /dev/lfcs_vg/data); printf 'UUID=%s /mnt/lfcs/lvm ext4 defaults 0 2 # LFCS-LAB\n' "$u" >>/etc/fstab ;;
  storage-04) resize2fs /dev/lfcs_extend/data >/dev/null ;;
  storage-05) pvcreate -ff -y /dev/lfcs-disk2 >/dev/null; vgextend lfcs_xfs /dev/lfcs-disk2 >/dev/null; lvextend -L +96M /dev/lfcs_xfs/logs >/dev/null; xfs_growfs /mnt/lfcs/xfs >/dev/null ;;
  storage-06) mkswap /dev/lfcs-disk3 >/dev/null; swapon /dev/lfcs-disk3; u=$(blkid -s UUID -o value /dev/lfcs-disk3); printf 'UUID=%s none swap sw 0 0 # LFCS-LAB\n' "$u" >>/etc/fstab ;;
  storage-07) sed -i '/00000000-0000-0000-0000-000000000000/d' /etc/fstab; u=$(blkid -s UUID -o value /dev/lfcs-disk1); printf 'UUID=%s /mnt/lfcs/data ext4 defaults 0 2 # LFCS-LAB\n' "$u" >>/etc/fstab; mount -a ;;
  storage-08) find /mnt/lfcs/data/generated -type f -delete ;;
  storage-09) kill "$(cat /run/lfcs-lab/leak.pid)"; wait "$(cat /run/lfcs-lab/leak.pid)" 2>/dev/null || true ;;
  storage-10) sudo -u student git -C /srv/lfcs/repo merge feature/banner >/dev/null 2>&1 || true; printf 'Base\nOperations\nNetworking\n' >/srv/lfcs/repo/banner.txt; chown student:student /srv/lfcs/repo/banner.txt; sudo -u student git -C /srv/lfcs/repo add banner.txt; sudo -u student git -C /srv/lfcs/repo commit -m merge >/dev/null ;;
  storage-12) openssl req -x509 -newkey rsa:2048 -nodes -subj /CN=secure.lfcs.internal -days 30 -keyout /etc/lfcs/tls/server.key -out /etc/lfcs/tls/server.crt >/dev/null 2>&1; chmod 0600 /etc/lfcs/tls/server.key; sed -i 's|missing.key|server.key|' /etc/nginx/sites-available/lfcs-tls; nginx -t; systemctl enable --now nginx; systemctl reload nginx ;;
  day5-readiness) mkfs.ext4 -F -L READY /dev/lfcs-disk1 >/dev/null; mkdir -p /mnt/lfcs/data; mount /dev/lfcs-disk1 /mnt/lfcs/data; u=$(blkid -s UUID -o value /dev/lfcs-disk1); printf 'UUID=%s /mnt/lfcs/data ext4 defaults 0 2 # LFCS-LAB\n' "$u" >>/etc/fstab; mkswap /dev/lfcs-disk3 >/dev/null; swapon /dev/lfcs-disk3; s=$(blkid -s UUID -o value /dev/lfcs-disk3); printf 'UUID=%s none swap sw 0 0 # LFCS-LAB\n' "$s" >>/etc/fstab; sudo -u student git -C /srv/lfcs/repo merge feature/banner >/dev/null 2>&1 || true; printf 'Base\nOperations\nNetworking\n' >/srv/lfcs/repo/banner.txt; chown student:student /srv/lfcs/repo/banner.txt; sudo -u student git -C /srv/lfcs/repo add banner.txt; sudo -u student git -C /srv/lfcs/repo commit -m merge >/dev/null; openssl req -x509 -newkey rsa:2048 -nodes -subj /CN=ready.lfcs.internal -days 30 -keyout /etc/lfcs/tls/server.key -out /etc/lfcs/tls/server.crt >/dev/null 2>&1; chmod 0600 /etc/lfcs/tls/server.key ;;

  *) echo "no full regression solution for $sid" >&2; exit 2 ;;
esac
