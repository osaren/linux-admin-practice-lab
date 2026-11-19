#!/usr/bin/env bash
set -euo pipefail
id=${1:?scenario id required}
case "$id" in
  sysinfo-01) uname -r >/tmp/kernel-release; sysctl -n vm.overcommit_memory >/tmp/overcommit-value; systemctl get-default >/tmp/default-target ;;
  cron-02) printf '15 7 * * 1,3,5 /usr/local/bin/alder-backup --incremental\n' | crontab -u student -; rm -f /etc/cron.d/alder-backup ;;
  operations-01) sed -i 's/acorn-ap1/acorn-api/;s/Restart=no/Restart=on-failure/' /etc/systemd/system/acorn-api.service; systemctl daemon-reload; systemctl enable --now acorn-api ;;
  operations-07) sysctl -q -w vm.swappiness=15; printf 'vm.swappiness = 15\n' >/etc/sysctl.d/90-lfcs-swappiness.conf; sysctl --system >/dev/null ;;
  iptables-10) mkdir -p /etc/iptables; ip netns exec router1 bash -c 'sysctl -q -w net.ipv4.ip_forward=1; iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT; iptables -A FORWARD -s 10.10.1.0/24 -d 10.10.3.10 -p tcp --dport 9130 -j ACCEPT; iptables-save > /etc/iptables/lfcs-router.v4' ;;
  networking-02) ip netns exec node2 ip route add 10.10.3.0/24 via 10.10.2.1; cat >/etc/netplan/90-lfcs-node2.yaml <<'EOF'
network:
  version: 2
  ethernets:
    lfcs-node2:
      match:
        name: node2-placeholder
      routes:
        - to: 10.10.3.0/24
          via: 10.10.2.1
EOF
  ;;
  networking-07) echo '10.10.2.10 api.internal' >>/etc/netns/node1/hosts ;;
  ssh-match-01) sed -i '/Match User buildbot/,$c\Match User buildbot\n    PasswordAuthentication no\n    PubkeyAuthentication yes' /etc/lfcs-lab/sshd-match.conf; sshd -t -f /etc/lfcs-lab/sshd-match.conf ;;
  nginx-03) cat >/etc/nginx/sites-available/lfcs-ext-proxy <<'EOF'
server { listen 8113; location / { proxy_set_header Host $host; proxy_pass http://10.10.2.10:8080; } }
EOF
    ln -sf /etc/nginx/sites-available/lfcs-ext-proxy /etc/nginx/sites-enabled/lfcs-ext-proxy; nginx -t; systemctl enable --now nginx; systemctl reload nginx ;;
  advanced-08) sed -i 's/10.10.3.10:8081/10.10.3.10:8080/' /etc/nginx/sites-available/lfcs-lb; nginx -t; systemctl reload nginx ;;
  find-02) find /srv/lfcs/find -type f -name '*.conf' -newermt 2026-08-20 -print | sort >/tmp/recent-configs ;;
  text-02) grep -E '^.*\|/api/[^|]*\|4[0-9]{2}\|.*Mobile$' /var/log/lfcs/agent.log >/tmp/mobile-errors ;;
  archive-02) d=$(mktemp -d); tar -xzf /srv/lfcs/archives/records.tar.gz -C "$d"; tar -C "$d" -cJf /tmp/records.tar.xz .; rm -rf "$d" ;;
  process-02) p=$(cat /run/lfcs-lab/extended-walnut.pid); printf '%s\n' "$p" "$(readlink -f /proc/$p/exe)" "$(lsof -Fn -a -p "$p" 2>/dev/null | sed -n 's|^n\(/srv/lfcs/process/walnut.data\)$|\1|p')" >/tmp/walnut-report; renice 12 -p "$p" >/dev/null ;;
  advanced-09) sed -i 's|/srv/lfcs/shrae .*|/srv/lfcs/share 10.10.1.0/24(rw,sync,no_subtree_check)|' /etc/exports; exportfs -ra ;;
  sshfs-01) sudo -u student sshfs -o IdentityFile=/srv/lfcs/keys/exam,StrictHostKeyChecking=no,UserKnownHostsFile=/dev/null,ro student@10.10.2.10:/srv/lfcs/node2 /mnt/lfcs/remote ;;
  lvm-03) lvextend -L +80M /dev/garden/data >/dev/null; resize2fs /dev/garden/data >/dev/null ;;
  mount-03) u=$(blkid -s UUID -o value /dev/lfcs-disk1); sed -i '/# LFCS-LAB/d' /etc/fstab; echo "UUID=$u /mnt/lfcs/recovery ext4 defaults,noexec 0 2 # LFCS-LAB" >>/etc/fstab; mount -a ;;
  docker-02) docker rm -f web-ivy >/dev/null; docker run -d --name web-ivy -p 8132:80 --memory 96m -e LFCS_STAGE=exam -v /srv/lfcs/ivy:/usr/share/nginx/html:ro nginx:alpine >/dev/null ;;
  sudo-01) echo 'maren ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx' >/etc/sudoers.d/91-lfcs-maren; chmod 0440 /etc/sudoers.d/91-lfcs-maren; visudo -cf /etc/sudoers.d/91-lfcs-maren >/dev/null ;;
  limits-02) cat >/etc/security/limits.d/92-lfcs-batch.conf <<'EOF'
@batch soft nproc 64
@batch hard nproc 96
@batch - maxlogins 3
EOF
  ;;
  git-02) sudo -u student git -C /srv/lfcs/git/banner merge feature/teal >/dev/null 2>&1 || true; printf 'Base\nOperations\nTeal\n' >/srv/lfcs/git/banner/banner.txt; chown student:student /srv/lfcs/git/banner/banner.txt; sudo -u student git -C /srv/lfcs/git/banner add banner.txt; sudo -u student git -C /srv/lfcs/git/banner commit -m 'integrate teal' >/dev/null ;;
  source-01) cd /usr/local/src/leafutil; ./configure --prefix=/usr --disable-ipv6; make; make install ;;
  storage-11) openssl req -x509 -newkey rsa:2048 -nodes -subj /CN=lfcs.internal -days 30 -keyout /etc/lfcs/tls/server.key -out /etc/lfcs/tls/server.crt >/dev/null 2>&1; chmod 0600 /etc/lfcs/tls/server.key ;;
  virt-08) cat >/srv/lfcs/virt/create-birch.sh <<'EOF'
#!/bin/bash
virt-install --name exam-birch --memory 1024 --vcpus 2 --import --disk path=/srv/lfcs/virt/exam-birch.qcow2,bus=virtio --network network=default --graphics none --noautoconsole --print-xml
EOF
    chmod 0755 /srv/lfcs/virt/create-birch.sh ;;
  *) echo "no regression solution for $id" >&2; exit 2 ;;
esac
