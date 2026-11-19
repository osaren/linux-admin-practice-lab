"""Additional focused LFCS scenarios. Solutions deliberately live elsewhere."""

def E(id, day, domain, host, minutes, title, requirements, skills, hints=None, difficulty="medium"):
    if hints is None:
        hints = [
            f"Inspect the existing {skills[0]} state before changing it.",
            "Use the subsystem's validation or inspection command and compare runtime with persistent state.",
            "Work one requirement at a time, then validate the exact final state the task requests.",
        ]
    return dict(id=id, day=day, domain=domain, host=host, minutes=minutes,
                title=title, requirements=requirements, hints=hints,
                skills=skills, difficulty=difficulty)

EXTENDED_LABS = []
add = EXTENDED_LABS.append

# Operations & Deployment: inspection, systemd, scheduling, processes, builds,
# Docker, time synchronisation, and compact virtualization practice.
add(E("sysinfo-01",1,"operations","lfcs",4,"Produce an exact system report",[
    "Write only the running kernel release to /tmp/kernel-release.",
    "Write only the current vm.overcommit_memory value to /tmp/overcommit-value.",
    "Write the current default systemd target to /tmp/default-target."],["system information","sysctl","systemd targets"], difficulty="easy"))
add(E("sysinfo-02",1,"operations","lfcs",5,"Inspect boot and clock state",[
    "Create /tmp/boot-clock-report with exactly three lines: the static hostname, configured timezone, and system boot ID, in that order.",
    "Do not include labels or extra whitespace."],["system information","timedatectl","procfs"], difficulty="easy"))

_systemd = [
 ("systemd-04","Repair a service identity",["Repair alder-worker so it runs as user svc-alder, becomes active, and is enabled.","Do not change the supplied executable."],"systemd broken units"),
 ("systemd-05","Apply a systemd override",["Use a drop-in override for pine-api so APP_MODE=production reaches the service process.","Keep the vendor unit unchanged; restart the service and leave it enabled."],"systemd overrides"),
 ("systemd-06","Recover a masked service",["Make juniper-agent unmasked, active, and enabled at boot.","Configure restart-on-failure without editing its executable."],"systemd masked units"),
 ("systemd-07","Repair service ordering",["Configure spruce-web to require and start after spruce-data.","Enable and start both services; the web service must observe the data-ready marker."],"systemd dependencies"),
 ("systemd-08","Diagnose an environment failure",["Repair hemlock-job using its existing EnvironmentFile so it writes green to /run/hemlock-result.","Use restart-on-failure and leave it active and enabled."],"systemd environment"),
]
for sid,title,req,skill in _systemd: add(E(sid,1,"operations","lfcs",7,title,req,[skill,"journalctl"]))

add(E("cron-02",1,"operations","lfcs",8,"Migrate a system cron job",[
    "Move the existing alder-backup command from /etc/cron.d/alder-backup into student's crontab.",
    "Run it at 07:15 every Monday, Wednesday, and Friday; remove the old system job without altering the command."],["cron migration","user crontab"], difficulty="hard"))
add(E("cron-03",1,"operations","lfcs",6,"Repair a root cron schedule",[
    "Repair /etc/cron.d/maple-prune so root runs the supplied program at 02:40 on the first day of every month.",
    "Correct file ownership and mode and preserve the program path."],["cron syntax","system cron"] ))
add(E("cron-04",1,"operations","lfcs",6,"Configure periodic anacron work",[
    "Add a job named cedar-index to /etc/anacrontab with period 7 days and delay 12 minutes.",
    "It must run /usr/local/bin/cedar-index as root without damaging existing entries."],["anacron","scheduling"] ))
add(E("process-02",1,"operations","lfcs",8,"Investigate a process and its files",[
    "Identify the process carrying LFCS_ROLE=walnut and write its PID, executable path, and open data-file path as three unlabeled lines in /tmp/walnut-report.",
    "Change only that process to nice value 12 and leave it running."],["process investigation","procfs","lsof"], difficulty="hard"))
add(E("source-01",1,"operations","lfcs",10,"Build and install a tiny source package",[
    "Build the project in /usr/local/src/leafutil using its configure workflow with prefix /usr and IPv6 disabled.",
    "Install it so /usr/bin/leafutil exists and reports prefix=/usr ipv6=disabled."],["source compilation","configure make install"], difficulty="hard"))
add(E("docker-01",1,"operations","lfcs",6,"Inspect a running Docker container",[
    "Inspect container web-fern and write its container IP, /usr/share/nginx/html mount source, published host port, and LFCS_STAGE value to /tmp/web-fern-report, one value per line.",
    "Do not recreate or stop the container."],["Docker inspect","containers"] ))
add(E("docker-02",1,"operations","lfcs",9,"Repair a constrained Docker service",[
    "Replace the broken web-ivy container with a running nginx:alpine container of the same name.",
    "Publish host TCP 8132 to container port 80, mount /srv/lfcs/ivy read-only at /usr/share/nginx/html, set LFCS_STAGE=exam, and enforce a 96 MiB memory limit."],["Docker run","Docker resources","containers"], difficulty="hard"))
add(E("timesync-01",2,"operations","lfcs",7,"Repair systemd time synchronisation",[
    "Configure systemd-timesyncd with NTP=time.cloudflare.com and FallbackNTP=ntp.ubuntu.com.",
    "Set PollIntervalMinSec=32 and PollIntervalMaxSec=1024, validate the configuration, and leave time synchronisation enabled."],["systemd-timesyncd","timedatectl"] ))
add(E("timesync-02",2,"operations","lfcs",6,"Troubleshoot timesyncd policy",[
    "Remove the invalid lab time source and configure 1.1.1.1 as the primary NTP server with ConnectionRetrySec=30.",
    "Leave systemd-timesyncd active and enabled."],["systemd-timesyncd","service troubleshooting"] ))

_virt = [
 ("virt-01","Inventory libvirt domains",["Using the libvirt test connection, create /tmp/virt-list with the output of both active-only and all-domain listings.","The report must include the test domain and preserve both command headings ACTIVE and ALL."],"virsh list"),
 ("virt-02","Inspect domain resources",["Using test:///default, record the test domain's name, state, maximum memory in KiB, and vCPU count in /tmp/virt-dominfo, one value per line.","Obtain the values from virsh rather than reading domain XML directly."],"virsh dominfo"),
 ("virt-03","Prepare safe lifecycle commands",["Complete /srv/lfcs/virt/lifecycle.sh so it starts, gracefully shuts down, force-stops, enables autostart, disables autostart, and undefines domain exam-elm using test:///default.","Keep the script non-interactive and syntactically valid; do not execute the undefine sequence."],"virsh lifecycle"),
 ("virt-04","Create a valid domain definition",["Complete /srv/lfcs/virt/exam-ash.xml for domain exam-ash with 768 MiB current/max memory and 2 vCPUs.","Use a virtio disk source /srv/lfcs/virt/exam-ash.qcow2 and a network interface on the default network."],"virsh define XML"),
 ("virt-05","Modify domain XML safely",["Edit /srv/lfcs/virt/exam-oak.xml so the domain has 3 vCPUs, 1024 MiB memory, and autostart intent recorded as enabled in metadata.","Keep its name, UUID, disk, and network unchanged and make the XML well-formed."],"virsh edit XML"),
 ("virt-06","Inspect a qcow2 image",["Create /tmp/exam-maple-info from qemu-img info --output=json for /srv/lfcs/virt/exam-maple.qcow2.","Do not change the image; the report must identify qcow2 and 64 MiB virtual size."],"qemu-img info"),
 ("virt-07","Resize a sparse virtual disk",["Increase /srv/lfcs/virt/exam-willow.qcow2 from 48 MiB to exactly 112 MiB using qemu-img.","Keep qcow2 format and do not allocate its full virtual capacity."],"qemu-img resize"),
 ("virt-08","Construct a virt-install command",["Complete /srv/lfcs/virt/create-birch.sh with one virt-install command for name exam-birch, 1024 MiB RAM, 2 vCPUs, importing /srv/lfcs/virt/exam-birch.qcow2 as virtio, default network, no graphics, and no autostart.","The script must be syntactically valid; do not launch a nested VM."],"virt-install"),
 ("virt-09","Troubleshoot an install definition",["Repair /srv/lfcs/virt/create-cedar.sh so virt-install can print valid XML for exam-cedar without starting it.","Use 512 MiB RAM, 1 vCPU, the existing qcow2 disk, default network, import mode, no graphics, and the generic Linux 2022 OS variant."],"virt-install troubleshooting"),
]
for sid,title,req,skill in _virt: add(E(sid,4,"operations","lfcs",8,title,req,[skill,"virtualization"],difficulty="hard" if sid in ("virt-04","virt-08","virt-09") else "medium"))

# Networking: NetworkManager progression, ten iptables tasks, six nginx tasks,
# and three SSH Match tasks.
_networkmanager = [
 ("nmcli-01","Repair and activate a NetworkManager profile",[
     "Repair the supplied connection lfcs-cedar for dummy interface nmcedar0 so it uses 198.51.100.20/24, supplies no default route, and is active.",
     "Keep the profile persistent and do not change the VM's management connection."],"NetworkManager profile repair","medium"),
 ("nmcli-02","Add a persistent profile route",[
     "Using the existing active connection lfcs-aspen on nmaspen0, add a persistent route to 198.51.100.0/24 via 192.0.2.1.",
     "Reactivate the profile so the route is live, retain 192.0.2.20/24, and do not replace the normal default route."],"NetworkManager route persistence","medium"),
 ("nmcli-03","Resolve competing NetworkManager profiles",[
     "Make lfcs-maple the active and autoconnecting profile for nmaple0 with 203.0.113.30/24 and no default route.",
     "Leave lfcs-maple-old inactive with autoconnect disabled, and preserve the VM's existing management address and default route."],"NetworkManager profile precedence","hard"),
]
for sid,title,req,skill,difficulty in _networkmanager:
    add(E(sid,2,"networking","lfcs",8,title,req,[skill,"nmcli runtime validation"],difficulty=difficulty))

_iptables = [
 ("iptables-01","Block one inbound service",["On node2, block new TCP connections to port 9121 while preserving established traffic and SSH.","Use iptables and verify node1 can no longer connect; do not change the service."],"iptables INPUT"),
 ("iptables-02","Restrict a port by source",["On node2, permit node1 to reach TCP 9122 but reject node3 on that port.","Preserve established traffic and place rules so the source-specific allow actually matches."],"iptables source restriction"),
 ("iptables-03","Block selected outbound traffic",["On node1, block outbound TCP traffic to node3 port 9123 while retaining connectivity to node2 and DNS.","Use the OUTPUT chain and an exact destination."],"iptables OUTPUT"),
 ("iptables-04","Redirect a local port",["On node2, redirect local TCP port 8184 to the service listening on 8084.","Use the nat table OUTPUT path so curl to 127.0.0.1:8184 returns node2-ready."],"iptables REDIRECT"),
 ("iptables-05","Configure destination NAT",["On router1, forward TCP port 8185 arriving from node1 to node2:8080.","Enable forwarding and add only the filter/NAT rules needed for real connectivity."],"iptables DNAT"),
 ("iptables-06","Masquerade one subnet",["On router1, masquerade IPv4 traffic sourced from 10.10.1.0/24 when it leaves toward the management link.","Enable IPv4 forwarding and do not NAT traffic between the three lab subnets."],"iptables MASQUERADE"),
 ("iptables-07","Permit routed application traffic",["On router1, use a default-drop FORWARD policy but allow established traffic and node1 TCP access to node3 port 9127.","Other new node1-to-node3 TCP ports must remain blocked."],"iptables FORWARD"),
 ("iptables-08","Repair rule ordering",["Repair node2's INPUT chain so node1 reaches TCP 9128 but other lab sources remain rejected.","Keep the existing broad reject rule, moving or inserting rules so the specific exception is effective."],"iptables ordering"),
 ("iptables-09","Persist a host firewall chain",["Create host chain LFCS_PERSIST, jump to it from INPUT, and accept TCP 8139 from 10.10.1.0/24 before rejecting other sources.","Save a syntactically valid IPv4 ruleset to /etc/iptables/rules.v4 without disrupting Docker rules."],"iptables persistence"),
 ("iptables-10","Repair a compound firewall path",["On router1, make node1 reach node3:9130 through a default-drop FORWARD policy while node2 remains blocked from that destination port.","Allow return traffic, enable IPv4 forwarding, and save the router namespace rules to /etc/iptables/lfcs-router.v4."],"iptables compound"),
]
for sid,title,req,skill in _iptables: add(E(sid,2,"networking","router1" if sid in {"iptables-05","iptables-06","iptables-07","iptables-10"} else ("node1" if sid=="iptables-03" else "node2"),8,title,req,[skill,"network connectivity"],difficulty="hard" if sid in {"iptables-05","iptables-07","iptables-10"} else "medium"))

_nginx = [
 ("nginx-01","Add an isolated nginx listener",["Add a new enabled server without editing existing application sites; listen on all IPv4 addresses at port 8111 and return exactly amber-ready plus a newline.","Validate and reload nginx, leaving it active and enabled."],"nginx listener"),
 ("nginx-02","Repair a broken server block",["Repair the supplied alder site so nginx validates and serves /srv/lfcs/alder on TCP 8112.","Enable the site, reload the service, and preserve all other server blocks."],"nginx troubleshooting"),
 ("nginx-03","Create a reverse proxy",["Add a listener on 8113 that proxies requests to node2's existing HTTP backend.","Preserve the original Host header, validate, reload, and return backend=node2."],"nginx reverse proxy"),
 ("nginx-04","Configure path forwarding",["On port 8114, forward /api/ to node2:8080 while stripping the /api prefix; requests outside /api/ must return 404.","Do not change the backend or existing nginx sites."],"nginx path forwarding"),
 ("nginx-05","Serve on two listeners",["Create one enabled server that returns twin-ready on both ports 8115 and 8116.","Bind all IPv4 addresses, validate, reload, and leave nginx enabled."],"nginx multiple listeners"),
 ("nginx-06","Repair a TLS listener",["Repair the supplied TLS site on 8446 using the certificate and key under /etc/lfcs/tls/fern.","Ensure the key mode is 0600, nginx validates, and HTTPS returns fern-secure."],"nginx TLS"),
]
for sid,title,req,skill in _nginx: add(E(sid,2,"networking","lfcs",8,title,req,[skill,"HTTP validation"],difficulty="hard" if sid in {"nginx-04","nginx-06"} else "medium"))

_ssh = [
 ("ssh-match-01","Apply a Match User policy",["Repair /etc/lfcs-lab/sshd-match.conf so user buildbot may use public keys but not passwords, while the global PasswordAuthentication setting remains yes.","Terminate the Match block correctly and validate with sshd -t and effective configuration."],"SSH Match User"),
 ("ssh-match-02","Apply a Match Group policy",["In the supplied isolated configuration /etc/lfcs-lab/sshd-match.conf, disable X11 forwarding and force internal-sftp for members of sftp-only.","Keep student unaffected, validate syntax, and demonstrate effective values with sshd -T -C."],"SSH Match Group"),
 ("ssh-match-03","Repair Match scope",["Fix the supplied sshd configuration so PermitRootLogin no applies globally, deployer alone receives Banner /etc/issue.net, and following directives are global again.","Validate the file and write deployer's effective banner value to /tmp/deployer-banner."],"SSH Match All"),
]
for sid,title,req,skill in _ssh: add(E(sid,2,"networking","lfcs",8,title,req,[skill,"sshd validation"],difficulty="hard"))

# Storage additions.
_storage = [
 ("lvm-01","Migrate data off an LVM PV",["Move all allocated extents off /dev/lfcs-disk2 in VG orchard, remove that PV from orchard, and leave /mnt/lfcs/orchard mounted with its sentinel intact.","Create no new filesystem and do not shrink the logical volume."],"LVM pvmove"),
 ("lvm-02","Reuse a released physical volume",["Remove unused /dev/lfcs-disk2 from VG oldfruit and reuse it in a new VG named freshfruit.","Create a 96 MiB LV named crates, format it ext4, and mount it at /mnt/lfcs/crates."],"LVM VG migration"),
 ("lvm-03","Extend an ext4 logical volume",["Extend garden/data by at least 80 MiB using free VG space and grow its ext4 filesystem online.","Keep /mnt/lfcs/garden mounted and preserve sentinel data."],"LVM ext4 growth"),
 ("lvm-04","Extend XFS with a new PV",["Add /dev/lfcs-disk2 to VG observatory, extend logs by at least 96 MiB, and grow its mounted XFS filesystem.","Do not attempt to shrink XFS and preserve existing data."],"LVM XFS growth"),
 ("mount-01","Enforce noexec persistently",["Mount the ext4 filesystem on /dev/lfcs-disk1 at /mnt/lfcs/noexec with noexec and nosuid now and persistently by UUID.","The supplied executable must remain present but fail direct execution."],"mount options"),
 ("mount-02","Remount a filesystem read-only",["Remount /mnt/lfcs/archive read-only without data loss and record a UUID-based ro entry in /etc/fstab.","Validate with findmnt and mount -a."],"mount remount"),
 ("mount-03","Repair a broken fstab entry",["Repair only the LFCS-LAB entry in /etc/fstab so /dev/lfcs-disk1 mounts as ext4 at /mnt/lfcs/recovery with defaults,noexec.","Use its real UUID, validate with mount -a, and leave it mounted."],"fstab troubleshooting"),
 ("nfs-01","Repair an NFS export and client mount",["Export /srv/lfcs/projects read-write only to 10.10.1.0/24 and activate the export.","From node1, mount 10.10.0.2:/srv/lfcs/projects at /mnt/lfcs/projects and add that exact persistent _netdev NFS entry without changing unrelated exports."],"NFS server client"),
 ("sshfs-01","Create a key-based SSHFS mount",["As student, mount node2:/srv/lfcs/node2 at /mnt/lfcs/remote using the supplied exam key.","Make it read-only, ensure backend content is readable, and do not weaken the private key permissions."],"SSHFS"),
 ("nbd-01","Attach and mount an NBD export",["Start the supplied NBD export named amber, attach it to /dev/nbd0, format it ext4, and mount it at /mnt/lfcs/amber.","Write amber-ready to /mnt/lfcs/amber/sentinel, then leave the connection and mount active."],"NBD lifecycle"),
 ("autofs-01","Configure an on-demand NFS mount",["Configure autofs so accessing /mnt/lfcs/on-demand/projects mounts localhost:/srv/lfcs/projects as an actual NFS filesystem (use the autofs nobind option).","Use an indirect map, leave autofs active and enabled, and do not add the mount to fstab."],"autofs NFS"),
 ("swap-01","Create persistent file-backed swap",["Create a 64 MiB sparse-compatible swap file at /var/lib/lfcs-lab/exam.swap with mode 0600.","Activate it and add an exact persistent fstab entry without changing existing swap devices."],"swap file"),
]
for sid,title,req,skill in _storage: add(E(sid,3,"storage","node1" if sid == "nfs-01" else "lfcs",9,title,req,[skill,"storage validation"],difficulty="hard" if sid.startswith("lvm-") or sid in {"nfs-01","nbd-01"} else "medium"))

# Essential Commands: controlled datasets make every grader inspect actual output.
_commands = [
 ("find-01","Find by owner and size",["Copy regular files under /srv/lfcs/find owned by hazel and larger than 12 KiB into /tmp/hazel-large without copying directory structure.","Do not copy matches from the destination back into itself."],"find owner size"),
 ("find-02","Find by date and name",["Write sorted paths of regular *.conf files modified on or after 2026-08-20 into /tmp/recent-configs.","Search only /srv/lfcs/find and use exact file dates."],"find newermt name"),
 ("find-03","Find exact permissions",["Move regular files with mode exactly 0640 from /srv/lfcs/find/perm into /srv/lfcs/quarantine.","Files with any other mode must remain in place."],"find permissions"),
 ("find-04","Find by group and age",["Delete regular *.tmp files in /srv/lfcs/find/cache owned by group cacheops and older than 30 minutes.","Preserve newer files and files from other groups."],"find group mmin"),
 ("find-05","Combine name predicates",["Create /tmp/image-list containing sorted paths of regular files under /srv/lfcs/find/media whose names end in .jpg or .png, case-insensitively.","Exclude every directory named archive and its contents."],"find logic prune"),
 ("find-06","Find SUID executables",["Write device, inode, mode, owner, and path for every SUID regular executable under /srv/lfcs/find/bin to /tmp/suid-audit.","Use stat output and sort by path."],"find SUID stat"),
 ("find-07","Find by multiple time windows",["Copy files under /srv/lfcs/find/inbox newer than /srv/lfcs/markers/start and older than /srv/lfcs/markers/end into /tmp/window.","Preserve timestamps and do not include directories."],"find newer reference"),
 ("find-08","Find and safely remove empty data",["Remove only empty regular files below /srv/lfcs/find/staging and then write the remaining regular-file count to /tmp/staging-count.","Do not remove empty directories."],"find empty delete"),
 ("text-01","Summarise an access log",["From /var/log/lfcs/access.log, write a descending request count by client IP for responses with status 5xx to /tmp/5xx-by-ip as COUNT IP.","Sort ties by IP ascending."],"awk sort uniq"),
 ("text-02","Filter with compound regular expressions",["Extract lines from /var/log/lfcs/agent.log whose path starts /api/, status is 400–499, and user agent ends Mobile into /tmp/mobile-errors.","Preserve source order and exact lines."],"grep extended regex"),
 ("text-03","Replace a delimited field",["In /srv/lfcs/app/users.csv, change shell /bin/sh to /bin/bash only for records whose role field is operator.","Preserve comments, field order, and every other record."],"sed fields"),
 ("text-04","Join and report configuration drift",["Create /tmp/config-drift showing sorted keys whose values differ between /srv/lfcs/app/expected.conf and actual.conf, one key per line.","Ignore comments and blank lines."],"awk diff"),
 ("text-05","Extract a timed error window",["From /var/log/lfcs/service.log, output only ERROR messages between 10:15:00 and 10:45:59 inclusive to /tmp/error-window, without timestamps or levels.","Preserve message order."],"awk regex logs"),
 ("text-06","Normalise and deduplicate data",["Create /tmp/team-names from /srv/lfcs/app/teams.txt by trimming surrounding whitespace, converting to lowercase, removing blank/comment lines, and deduplicating in sorted order.","The output must end with one newline."],"sed tr sort uniq"),
 ("archive-01","Inspect archives without extraction",["Write a sorted member list common to both supplied archives into /tmp/common-members.","Do not extract either archive and omit directory-only members."],"tar archive inspection"),
 ("archive-02","Recompress while preserving input",["Create /tmp/records.tar.xz from /srv/lfcs/archives/records.tar.gz using maximum xz compression.","Preserve the original archive and ensure both contain equivalent members and contents."],"tar recompression"),
 ("archive-03","Extract a selected subtree",["Extract only conf.d/ and its contents from /srv/lfcs/archives/bundle.tar.bz2 into /tmp/bundle-selected.","Do not extract logs/ or README and preserve stored modes."],"tar selective extract"),
 ("redirection-01","Separate standard streams",["Run /usr/local/bin/lfcs-streams once, writing stdout to /tmp/stream.out and stderr to /tmp/stream.err.","Write its numeric exit status alone to /tmp/stream.status."],"redirection exit status"),
 ("redirection-02","Append combined output",["Run /usr/local/bin/lfcs-streams twice and append both stdout and stderr, in emitted order, to /tmp/stream-combined.","Do not truncate the supplied first line."],"redirection append"),
 ("redirection-03","Pipe only standard output",["Run /usr/local/bin/lfcs-streams and count only stdout lines into /tmp/stdout-count while writing stderr unchanged to /tmp/pipeline.err.","Record the producer's exit code in /tmp/producer.status."],"pipelines pipefail"),
 ("links-01","Repair symbolic links",["Repair /srv/lfcs/links/current so it is a relative symbolic link to releases/v2 and resolves to the supplied version file.","Do not modify releases/v1 or releases/v2."],"symbolic links"),
 ("links-02","Create a hard-link backup",["Create /srv/lfcs/links/config.backup as a hard link to config.live.","Both names must share an inode and link count 2; preserve content and mode."],"hard links"),
 ("permissions-01","Configure a shared directory",["Set /srv/lfcs/shared to group editors with SGID and mode 2770.","Existing tool.sh must be executable by owner/group but inaccessible to others and retain correct group ownership."],"permissions SGID"),
 ("permissions-02","Repair a SUID helper",["Set /srv/lfcs/bin/report-id to root:auditors with mode 4750.","The executable bits and SUID bit must all be present; do not set SGID or world access."],"permissions SUID"),
 ("attributes-01","Protect and inspect a ledger",["Make /srv/lfcs/ledger/current.log append-only and /srv/lfcs/ledger/schema.conf immutable.","Write lsattr output for both files to /tmp/ledger-attributes."],"file attributes"),
 ("git-01","Identify the correct feature branch",["In /srv/lfcs/git/service, identify the branch containing both FEATURE_GATE=true and API_LEVEL=7 and write its name to /tmp/selected-branch.","Do not merge or modify the repository."],"Git branch investigation"),
 ("git-02","Merge and resolve a small conflict",["In /srv/lfcs/git/banner, merge branch feature/teal into main.","Resolve banner.txt so it contains Base, Operations, and Teal exactly once, commit with message integrate teal, and leave a clean tree."],"Git merge conflict"),
]
for sid,title,req,skill in _commands: add(E(sid,5,"commands","lfcs",7,title,req,[skill,"essential commands"],difficulty="hard" if sid in {"find-05","find-07","text-04","redirection-03","git-02"} else "medium"))

# Users & Groups.
_users = [
 ("usermod-01","Modify a user without losing groups",["Change maren's primary group to platform, add supplementary group incident without removing analytics, and set shell /bin/bash.","Keep UID and home path unchanged."],"user modification"),
 ("usermod-02","Move a user's home safely",["Move devin's home from /home/devin to /srv/home/devin using the account tools, preserving all files and ownership.","Set shell /bin/bash and leave UID/group memberships unchanged."],"usermod home"),
 ("usermod-03","Apply account ageing policy",["Set rhea's account expiry to 2026-09-20, maximum password age 21 days, minimum 2 days, and warning 5 days.","Do not lock the account or change its shell."],"password ageing"),
 ("usermod-04","Rename an account and group",["Rename user tempwriter to rowan and its private primary group to rowan; move the home to /home/rowan.","Preserve UID, supplementary group authors, and all home data ownership."],"user rename"),
 ("sudo-01","Grant one exact passwordless command",["Allow user maren to run /usr/bin/systemctl restart nginx as root without a password and no other new sudo command.","Put the rule in /etc/sudoers.d/91-lfcs-maren and validate it with visudo."],"sudo exact command"),
 ("sudo-02","Grant a group run-as rule",["Allow members of deployops to run /usr/bin/install -m 0644 * /srv/releases/ as user release, requiring their password.","Use /etc/sudoers.d/92-lfcs-deployops and do not grant a shell or ALL."],"sudo run-as group"),
 ("sudo-03","Repair a broken sudoers alias",["Repair /etc/sudoers.d/93-lfcs-monitor so group monitoring may passwordlessly run only /usr/bin/journalctl and /usr/bin/systemctl status *.","Use the existing command alias, secure mode, and visudo validation."],"sudoers alias"),
 ("sudo-04","Restrict a maintenance account",["Allow account backupbot to run /usr/bin/rsync * as user archive without a password.","Explicitly prevent sudo from preserving arbitrary environment variables and grant no other command."],"sudo restricted account"),
 ("env-01","Configure login and child scope",["Set LFCS_REGION=eu-west system-wide for login sessions and export PROJECT=cedar only for user maren.","Ensure both reach child processes; PROJECT must not appear for other users."],"environment scope"),
 ("env-02","Prepare defaults for future users",["Configure /etc/skel so future Bash users receive exported EDITOR=vim and umask 027 in .profile.","Create user sampleleaf afterward and verify its copied profile; do not alter existing users."],"etc skel"),
 ("env-03","Repair shell variable inheritance",["Repair /home/devin/.profile so BUILD_ROOT=/srv/build reaches child processes while LOCAL_NOTE remains shell-local.","Do not define either variable system-wide."],"shell export"),
 ("limits-01","Move a limit to persistent policy",["Remove the ineffective ulimit workaround from maren's .bashrc and set her soft/hard nofile limits to 4096/8192 in /etc/security/limits.d/91-lfcs.conf.","Preserve unrelated shell customisations."],"resource limits"),
 ("limits-02","Configure group resource limits",["For @batch, configure soft nproc 64, hard nproc 96, and maxlogins 3 in /etc/security/limits.d/92-lfcs-batch.conf.","Do not apply the limits globally and remove the supplied contradictory entry."],"group limits"),
]
for sid,title,req,skill in _users: add(E(sid,4,"users","lfcs",7,title,req,[skill,"users and groups"],difficulty="hard" if sid.startswith("sudo-") else "medium"))
