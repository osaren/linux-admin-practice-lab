"""Explicitly gated reference solutions; never imported into task metadata."""

SOLUTIONS = {
"sysinfo-01": r"""uname -r > /tmp/kernel-release
sysctl -n vm.overcommit_memory > /tmp/overcommit-value
systemctl get-default > /tmp/default-target""",
"sysinfo-02": r"""hostnamectl --static > /tmp/boot-clock-report
timedatectl show -p Timezone --value >> /tmp/boot-clock-report
cat /proc/sys/kernel/random/boot_id >> /tmp/boot-clock-report""",
"systemd-04": r"""sudo sed -i '/^\[Service\]/a User=svc-alder' /etc/systemd/system/alder-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now alder-worker""",
"systemd-05": r"""sudo systemctl edit pine-api
# Enter under [Service]: Environment=APP_MODE=production
sudo systemctl daemon-reload
sudo systemctl enable --now pine-api""",
"systemd-06": r"""sudo systemctl unmask juniper-agent
sudo sed -i 's/Restart=no/Restart=on-failure/' /etc/systemd/system/juniper-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now juniper-agent""",
"systemd-07": r"""sudo systemctl edit spruce-web
# Enter: [Unit], Requires=spruce-data.service, After=spruce-data.service
sudo systemctl daemon-reload
sudo systemctl enable --now spruce-data spruce-web""",
"cron-02": r"""(sudo crontab -u student -l 2>/dev/null; echo '15 7 * * 1,3,5 /usr/local/bin/alder-backup --incremental') | sudo crontab -u student -
sudo rm /etc/cron.d/alder-backup""",
"cron-03": r"""echo '40 2 1 * * root /usr/local/bin/maple-prune' | sudo tee /etc/cron.d/maple-prune
sudo chown root:root /etc/cron.d/maple-prune
sudo chmod 0644 /etc/cron.d/maple-prune""",
"source-01": r"""cd /usr/local/src/leafutil
sudo ./configure --prefix=/usr --disable-ipv6
sudo make
sudo make install
/usr/bin/leafutil""",
"docker-01": r"""sudo docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' web-fern > /tmp/web-fern-report
sudo docker inspect -f '{{range .Mounts}}{{if eq .Destination \"/usr/share/nginx/html\"}}{{.Source}}{{end}}{{end}}' web-fern >> /tmp/web-fern-report
sudo docker inspect -f '{{(index (index .NetworkSettings.Ports \"80/tcp\") 0).HostPort}}' web-fern >> /tmp/web-fern-report
sudo docker inspect -f '{{range .Config.Env}}{{if eq . \"LFCS_STAGE=practice\"}}practice{{end}}{{end}}' web-fern >> /tmp/web-fern-report""",
"docker-02": r"""sudo docker rm -f web-ivy
sudo docker run -d --name web-ivy -p 8132:80 --memory 96m -e LFCS_STAGE=exam -v /srv/lfcs/ivy:/usr/share/nginx/html:ro nginx:alpine""",
"timesync-01": r"""sudoedit /etc/systemd/timesyncd.conf.d/95-lfcs-broken.conf
# [Time]
# NTP=time.cloudflare.com
# FallbackNTP=ntp.ubuntu.com
# PollIntervalMinSec=32
# PollIntervalMaxSec=1024
sudo systemctl enable --now systemd-timesyncd
timedatectl timesync-status""",
"nmcli-01": r"""nmcli -f all connection show lfcs-cedar
sudo nmcli connection modify lfcs-cedar ipv4.addresses 198.51.100.20/24 ipv4.never-default yes
sudo nmcli connection up lfcs-cedar
nmcli device show nmcedar0
ip address show nmcedar0
ip route""",
"nmcli-02": r"""nmcli -f all connection show lfcs-aspen
sudo nmcli connection modify lfcs-aspen +ipv4.routes "198.51.100.0/24 192.0.2.1"
sudo nmcli connection up lfcs-aspen
nmcli -g ipv4.routes connection show lfcs-aspen
ip route get 198.51.100.1""",
"nmcli-03": r"""nmcli connection show --active
sudo nmcli connection modify lfcs-maple-old connection.autoconnect no
sudo nmcli connection modify lfcs-maple connection.autoconnect yes ipv4.never-default yes
sudo nmcli connection up lfcs-maple
nmcli -f NAME,AUTOCONNECT connection show
nmcli device show nmaple0
ip route""",
"networking-10": r"""systemd-analyze cat-config systemd/timesyncd.conf
sudoedit /etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf
# [Time]
# NTP=time.cloudflare.com
sudo systemctl reset-failed systemd-timesyncd
sudo systemctl enable systemd-timesyncd
sudo systemctl restart systemd-timesyncd
systemctl is-active systemd-timesyncd
systemctl is-enabled systemd-timesyncd
systemd-analyze cat-config systemd/timesyncd.conf""",
"iptables-01": r"""sudo iptables -I INPUT 1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9121 -j DROP""",
"iptables-02": r"""sudo iptables -I INPUT 1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
sudo iptables -I INPUT 2 -s 10.10.1.0/24 -p tcp --dport 9122 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9122 -j REJECT""",
"iptables-04": r"""sudo iptables -t nat -A OUTPUT -p tcp -d 127.0.0.1 --dport 8184 -j REDIRECT --to-ports 8084""",
"iptables-05": r"""sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A PREROUTING -i eth1 -p tcp --dport 8185 -j DNAT --to-destination 10.10.2.10:8080
sudo iptables -A FORWARD -i eth1 -o eth2 -p tcp -d 10.10.2.10 --dport 8080 -j ACCEPT
sudo iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT""",
"iptables-09": r"""sudo iptables -I LFCS_PERSIST 1 -s 10.10.1.0/24 -p tcp --dport 8139 -j ACCEPT
sudo iptables -A LFCS_PERSIST -p tcp --dport 8139 -j REJECT
sudo sh -c 'iptables-save > /etc/iptables/rules.v4'
sudo iptables-restore --test < /etc/iptables/rules.v4""",
"nginx-01": r"""sudo tee /etc/nginx/sites-available/lfcs-ext-amber <<'EOF'
server { listen 8111; location / { return 200 \"amber-ready\\n\"; } }
EOF
sudo ln -s /etc/nginx/sites-available/lfcs-ext-amber /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl enable --now nginx && sudo systemctl reload nginx""",
"nginx-03": r"""sudo tee /etc/nginx/sites-available/lfcs-ext-proxy <<'EOF'
server { listen 8113; location / { proxy_set_header Host $host; proxy_pass http://10.10.2.10:8080; } }
EOF
sudo ln -s /etc/nginx/sites-available/lfcs-ext-proxy /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx""",
"ssh-match-01": r"""sudoedit /etc/lfcs-lab/sshd-match.conf
# Under Match User buildbot set PasswordAuthentication no and PubkeyAuthentication yes.
# Add Match All before later global directives if any.
sudo sshd -t -f /etc/lfcs-lab/sshd-match.conf
sudo sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=buildbot,host=localhost,addr=127.0.0.1""",
"mount-03": r"""UUID=$(sudo blkid -s UUID -o value /dev/lfcs-disk1)
sudo sed -i '/# LFCS-LAB/d' /etc/fstab
echo \"UUID=$UUID /mnt/lfcs/recovery ext4 defaults,noexec 0 2 # LFCS-LAB\" | sudo tee -a /etc/fstab
sudo mount -a
findmnt /mnt/lfcs/recovery""",
"find-02": r"""find /srv/lfcs/find -type f -name '*.conf' -newermt 2026-08-20 -print | sort > /tmp/recent-configs""",
"text-02": r"""grep -E '^.*\|/api/[^|]*\|4[0-9]{2}\|.*Mobile$' /var/log/lfcs/agent.log > /tmp/mobile-errors""",
"archive-02": r"""mkdir /tmp/records-work
tar -xzf /srv/lfcs/archives/records.tar.gz -C /tmp/records-work
tar -C /tmp/records-work -cJf /tmp/records.tar.xz -I 'xz -9' .""",
"sudo-01": r"""echo 'maren ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx' | sudo tee /etc/sudoers.d/91-lfcs-maren
sudo chmod 0440 /etc/sudoers.d/91-lfcs-maren
sudo visudo -cf /etc/sudoers.d/91-lfcs-maren""",
"limits-02": r"""sudo tee /etc/security/limits.d/92-lfcs-batch <<'EOF'
@batch soft nproc 64
@batch hard nproc 96
@batch - maxlogins 3
EOF""",
"git-02": r"""cd /srv/lfcs/git/banner
git merge feature/teal
printf 'Base\nOperations\nTeal\n' > banner.txt
git add banner.txt
git commit -m 'integrate teal'""",
"virt-07": r"""sudo qemu-img resize /srv/lfcs/virt/exam-willow.qcow2 112M
qemu-img info /srv/lfcs/virt/exam-willow.qcow2""",
"virt-08": r"""sudo tee /srv/lfcs/virt/create-birch.sh <<'EOF'
#!/bin/bash
virt-install --name exam-birch --memory 1024 --vcpus 2 --import --disk path=/srv/lfcs/virt/exam-birch.qcow2,bus=virtio --network network=default --graphics none --noautoconsole --print-xml
EOF
sudo chmod 0755 /srv/lfcs/virt/create-birch.sh
bash -n /srv/lfcs/virt/create-birch.sh""",
}

SOLUTIONS.update({
"selinux-01": r"""getenforce
sestatus
ls -Z /srv/lfcs-special/foundation/index.html
matchpathcon /srv/lfcs-special/foundation/index.html
ps -eZ | grep httpd
# Write only the requested five values, in order, to /tmp/lfcs-selinux-foundation.""",
"selinux-02": r"""sudo semanage fcontext -a -t httpd_sys_content_t '/srv/lfcs-special/context-site(/.*)?'
sudo restorecon -RF /srv/lfcs-special/context-site
sudo systemctl restart httpd
curl -fsS http://127.0.0.1/""",
"selinux-03": r"""sudo ausearch -if /var/log/audit/audit.log -m AVC -i | tail
sudo semanage port -a -t http_port_t -p tcp 8124
sudo systemctl enable --now httpd
curl -fsS http://127.0.0.1:8124/""",
"selinux-04": r"""sudo ausearch -if /var/log/audit/audit.log -m AVC -i | tail
# Record httpd_t, user_home_t, and read as the three diagnosis lines.
sudo semanage fcontext -a -t httpd_sys_content_t '/srv/lfcs-special/avc-site(/.*)?'
sudo restorecon -RF /srv/lfcs-special/avc-site
sudo systemctl restart httpd""",
"selinux-05": r"""getsebool httpd_can_network_connect
sudo setsebool -P httpd_can_network_connect on
sudo systemctl enable --now httpd lfcs-special-backend
curl -fsS http://127.0.0.1/""",
"selinux-06": r"""sudo ausearch -if /var/log/audit/audit.log -m AVC -i | tail
matchpathcon /srv/lfcs-special/transfer-site/index.html
sudo semanage fcontext -a -t httpd_sys_content_t '/srv/lfcs-special/transfer-site(/.*)?'
sudo restorecon -RF /srv/lfcs-special/transfer-site
sudo systemctl restart httpd""",
"ldap-01": r"""getent passwd root
getent passwd student
getent passwd directoryuser
getent group ldapops
sssctl domain-list
# Write the requested UID/GID/provider values to /tmp/lfcs-ldap-foundation.""",
"ldap-02": r"""sudoedit /etc/sssd/sssd.conf
# [sssd] services = nss, pam; domains = lfcs
# [domain/lfcs] id_provider = ldap; auth_provider = ldap
# ldap_uri = ldap://127.0.0.1
# ldap_search_base = dc=lfcs,dc=internal
# ldap_schema = rfc2307; ldap_id_use_start_tls = false
sudo chmod 0600 /etc/sssd/sssd.conf
sudo systemctl enable --now sssd
sudo sss_cache -E
getent passwd directoryuser; getent group ldapops; id directoryuser""",
"ldap-03": r"""sudo sssctl config-check
sudoedit /etc/sssd/sssd.conf
# Correct ldap_search_base to dc=lfcs,dc=internal.
sudo sss_cache -E
sudo systemctl restart sssd
getent passwd directoryuser""",
"ldap-04": r"""sudo systemctl status dirsrv@lfcs sssd
sudo systemctl enable --now dirsrv@lfcs
sudo sss_cache -E
sudo systemctl restart sssd
getent passwd directoryuser; getent group ldapops""",
"ldap-05": r"""sudoedit /etc/sssd/sssd.conf
# Correct auth_provider from deny to ldap, keeping id_provider = ldap.
sudo systemctl restart sssd
getent passwd directoryuser
sudo cat /var/lib/lfcs-special/credentials/directoryuser | sudo pamtester login directoryuser authenticate""",
})

FAMILY_GUIDANCE = {
    "find-": "Use find with the exact predicates in the task, validate with -print first, then apply the requested action. Compare the resulting paths with find/stat.",
    "text-": "Build the filter as a read-only grep -E/awk pipeline first, verify it, then redirect the exact final output to the requested path.",
    "archive-": "Use tar's list mode before extraction. Work in /tmp, preserve the source, and compare sorted member lists and extracted trees.",
    "virt-": "Use virsh -c test:///default and local --help/man pages. Store the requested final XML, report, or executable command script at the exact path.",
    "lvm-": "Inspect pvs/vgs/lvs first. Apply pv/vg/lv operations in dependency order, grow the filesystem with resize2fs or xfs_growfs, then verify mounts and sentinel data.",
    "usermod-": "Record id/getent output first, use usermod with -aG when retaining supplementary groups, then verify passwd, group, home, and ownership state.",
    "sudo-": "Write only the exact Cmnd_Spec to the requested /etc/sudoers.d fragment, chmod 0440, and validate with visudo -cf plus sudo -l -U.",
}

def solution_for(scenario_id):
    if scenario_id in SOLUTIONS: return SOLUTIONS[scenario_id]
    for prefix,text in FAMILY_GUIDANCE.items():
        if scenario_id.startswith(prefix): return text + "\n\nUse the task's exact values; the grader checks final state, not history."
    return "This retained scenario's solution is intentionally concise: use the three progressive hints, inspect its final-state checks, apply the exact requested state, then run ./bin/lfcs grade " + scenario_id + "."
