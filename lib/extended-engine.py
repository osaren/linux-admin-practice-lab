#!/usr/bin/env python3
"""State engine for the expanded, data-driven LFCS scenario families."""
import json
import configparser
import ipaddress
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else ""
ID = sys.argv[2] if len(sys.argv) > 2 else ""
if not re.fullmatch(r"[a-z0-9-]+", ID):
    raise SystemExit("LFCS extended engine: invalid scenario ID")
if not pathlib.Path('/usr/local/lib/lfcs/verify-guest.py').is_file() or subprocess.run(['/usr/local/lib/lfcs/verify-guest.py'], capture_output=True).returncode:
    raise SystemExit('LFCS extended engine: candidate guest marker missing')
import yaml
STATE = pathlib.Path("/var/lib/lfcs-lab")
RUN = pathlib.Path("/run/lfcs-lab")
OWNED = STATE / "extended-owned"
STUDENT_SUDOERS = pathlib.Path("/etc/sudoers.d/00-lfcs-student-admin")
TIMESYNC_BASELINE = pathlib.Path("/etc/systemd/timesyncd.conf.d/90-lfcs.conf")

def run(command, check=True, capture=False, user=None):
    argv = ["bash", "-lc", command]
    if user:
        argv = ["sudo", "-u", user, "-H", *argv]
    return subprocess.run(argv, text=True, check=check,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)

def out(command):
    return run(command, check=False, capture=True).stdout.strip()

def write(path, content, mode=None, owner=None):
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content).lstrip())
    if mode is not None: p.chmod(mode)
    if owner: shutil.chown(p, *owner.split(":"))

def restore_student_admin():
    write(STUDENT_SUDOERS, "student ALL=(ALL) NOPASSWD: ALL\n", 0o440, "root:root")

def restore_timesync_baseline():
    write(TIMESYNC_BASELINE,
          "[Time]\nNTP=time.cloudflare.com\nFallbackNTP=ntp.ubuntu.com\n")

def remove_export_path(export_path):
    """Remove a lab-owned export path while preserving every unrelated entry."""
    files = [pathlib.Path("/etc/exports")]
    exports_dir = pathlib.Path("/etc/exports.d")
    if exports_dir.exists():
        files.extend(exports_dir.glob("*.exports"))
    owned = re.compile(rf"^\s*{re.escape(export_path)}(?:\s|$)")
    for exports in files:
        if not exports.is_file():
            continue
        lines = exports.read_text().splitlines(keepends=True)
        retained = [line for line in lines if not owned.match(line.rstrip("\r\n"))]
        if retained != lines:
            exports.write_text("".join(retained))

def remove_autofs_entries(master_path, nfs_path):
    """Remove lab-owned autofs lines while retaining unrelated maps and comments."""
    master_files = [pathlib.Path("/etc/auto.master")]
    master_dir = pathlib.Path("/etc/auto.master.d")
    if master_dir.exists():
        master_files.extend(master_dir.iterdir())
    owned_master = re.compile(rf"^\s*{re.escape(master_path)}(?:\s|$)")
    for master in master_files:
        if not master.is_file():
            continue
        lines = master.read_text().splitlines(keepends=True)
        retained = [line for line in lines
                    if not owned_master.match(line.rstrip("\r\n"))]
        if retained != lines:
            master.write_text("".join(retained))

    owned_source = re.compile(rf"^[^#\n]*{re.escape(nfs_path)}(?:\s|$)")
    for mapping in pathlib.Path("/etc").glob("auto.*"):
        if not mapping.is_file():
            continue
        lines = mapping.read_text().splitlines(keepends=True)
        retained = [line for line in lines
                    if not owned_source.match(line.rstrip("\r\n"))]
        if retained != lines:
            mapping.write_text("".join(retained))

def check(message, command):
    ok = run(command, check=False, capture=True).returncode == 0
    print(("PASS" if ok else "FAIL") + "|" + message)

def check_bool(message, ok):
    print(("PASS" if ok else "FAIL") + "|" + message)

def fstab_entry(target, fstype, *, uuid_device=None, source=None, required_options=(), normalize_target=False):
    """Validate parsed fstab state without depending on quotes or whitespace."""
    try:
        payload = json.loads(out("findmnt --fstab --json -o SOURCE,TARGET,FSTYPE,OPTIONS"))
    except (json.JSONDecodeError, OSError):
        return False
    expected_source = source
    if uuid_device is not None:
        uuid = out(f"blkid -s UUID -o value {shlex.quote(uuid_device)}")
        if not uuid:
            return False
        expected_source = f"UUID={uuid}"
    for entry in payload.get("filesystems", []):
        actual_source = str(entry.get("source", "")).replace('"', "")
        options = set(str(entry.get("options", "")).split(","))
        actual_target = entry.get("target")
        if normalize_target:
            actual_target = str(actual_target).rstrip("/")
        if (actual_target == target and entry.get("fstype") == fstype
                and (expected_source is None or actual_source == expected_source)
                and set(required_options).issubset(options)):
            return True
    return False

def mount_entry(target, fstypes, *, source=None, required_options=(), context=""):
    """Validate the effective leaf mount semantically through findmnt JSON."""
    if isinstance(fstypes, str):
        fstypes = {fstypes}
    else:
        fstypes = set(fstypes)
    try:
        payload = json.loads(out(
            f"{context}findmnt --json --target {shlex.quote(target)} -o SOURCE,TARGET,FSTYPE,OPTIONS"))
    except (json.JSONDecodeError, OSError):
        return False
    required = set(required_options)
    for entry in payload.get("filesystems", []):
        actual_source = str(entry.get("source", "")).replace('"', "")
        options = set(str(entry.get("options", "")).split(","))
        if (entry.get("target") == target and entry.get("fstype") in fstypes
                and (source is None or actual_source == source)
                and required.issubset(options)):
            return True
    return False

def nfs_client_mount_contexts(*, cleanup=False):
    """Find the node1 shell's private mount namespace created by ip netns exec.

    Cleanup also visits obsolete namespaces, but only the reserved projects
    mount. Grading considers the current node1 network namespace and the main
    mount namespace used by nsenter --net solutions.
    """
    target = "/mnt/lfcs/projects"
    try: node_net = pathlib.Path("/var/run/netns/node1").stat().st_ino
    except OSError: return []
    contexts = []
    seen = set()
    candidates = list(pathlib.Path("/proc").glob("[0-9]*"))
    for proc in candidates:
        try:
            mount_ns = (proc / "ns/mnt").stat().st_ino
            network_ns = (proc / "ns/net").stat().st_ino
            if mount_ns in seen or (not cleanup and network_ns != node_net): continue
            entries = [line.split() for line in (proc / "mountinfo").read_text().splitlines()]
            if not any(len(row) > 6 and row[4] == target for row in entries): continue
            seen.add(mount_ns)
            contexts.append(f"nsenter --mount={proc}/ns/mnt --net=/var/run/netns/node1 -- ")
        except OSError: continue
    if not cleanup:
        contexts.append("nsenter --net=/var/run/netns/node1 -- ")
    return contexts

def nfs_client_mount_context():
    contexts = nfs_client_mount_contexts()
    for context in contexts:
        if mount_entry("/mnt/lfcs/projects", {"nfs", "nfs4"},
                       source="10.10.0.2:/srv/lfcs/projects", context=context):
            return context
    # Keep partial-credit checks in the same client namespace for invalid mounts.
    return contexts[0] if contexts else ""

def unmount_nfs_client_contexts():
    for context in nfs_client_mount_contexts(cleanup=True):
        run("timeout 5s " + context + "umount -l /mnt/lfcs/projects",
            check=False, capture=True)


def autofs_indirect_map(master_path, key, source):
    """Accept whitespace/quoting variants while binding one master to one map."""
    masters = [pathlib.Path("/etc/auto.master")]
    master_dir = pathlib.Path("/etc/auto.master.d")
    if master_dir.exists(): masters.extend(p for p in master_dir.iterdir() if p.is_file())
    maps = []
    for master in masters:
        if not master.is_file(): continue
        for raw in master.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line: continue
            try: fields = shlex.split(line)
            except ValueError: continue
            if len(fields) >= 2 and fields[0] == master_path:
                maps.append(pathlib.Path(fields[1]))
    for mapping in maps:
        if not mapping.is_file(): continue
        for raw in mapping.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line: continue
            try: fields = shlex.split(line)
            except ValueError: continue
            if len(fields) < 3 or fields[0] != key or fields[-1] != source:
                continue
            options = set(fields[1].removeprefix("-").split(","))
            if "fstype=nfs" in options and "nobind" in options and "ro" not in options:
                return True
    return False

def nm_profile_persistent(name):
    uuid = out(f"nmcli -g connection.uuid connection show {shlex.quote(name)}")
    if not uuid: return False
    root = pathlib.Path("/etc/NetworkManager/system-connections")
    for path in root.iterdir() if root.is_dir() else ():
        if not path.is_file(): continue
        parser = configparser.ConfigParser(interpolation=None)
        try: parser.read(path)
        except (OSError, configparser.Error): continue
        if (parser.get("connection", "id", fallback="") == name and
                parser.get("connection", "uuid", fallback="") == uuid):
            return True
    def walk(value):
        if isinstance(value, dict):
            nm = value.get("networkmanager")
            if isinstance(nm, dict) and str(nm.get("uuid")) == uuid and nm.get("name") == name:
                return True
            return any(walk(child) for child in value.values())
        if isinstance(value, list): return any(walk(child) for child in value)
        return False
    for path in pathlib.Path("/etc/netplan").glob("*.yaml"):
        try: data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError): continue
        if walk(data) and run("netplan generate", check=False, capture=True).returncode == 0:
            return True
    return False

def nfs_export_restricted(path, allowed_network):
    """Accept only active rw clients contained by the task's allowed network."""
    allowed=ipaddress.ip_network(allowed_network)
    found=False
    for raw in out("exportfs -s").splitlines():
        fields=raw.split()
        if not fields or fields[0] != path:
            continue
        found=True
        for spec in fields[1:]:
            client=spec.split("(",1)[0]
            options=(spec.split("(",1)[1].rstrip(")").split(",")
                     if "(" in spec else [])
            try:
                network=ipaddress.ip_network(
                    client if "/" in client else client+"/32", strict=False)
            except ValueError:
                return False
            if not network.subnet_of(allowed) or "rw" not in options:
                return False
    return found

def net(ns, command, check_result=True):
    return run(f"ip netns exec {shlex.quote(ns)} bash -lc {shlex.quote(command)}", check=check_result)

def service(name, body):
    write(f"/etc/systemd/system/{name}.service", body)
    run("systemctl daemon-reload")

def stop_owned_processes(prefixes=None):
    for p in RUN.glob("extended-*.pid"):
        scenario = p.name.removeprefix("extended-").removesuffix(".pid")
        if prefixes and not any(scenario.startswith(prefix) for prefix in prefixes):
            continue
        try:
            pid = int(p.read_text().strip())
            marker = f"LFCS_EXTENDED_PID={scenario}".encode()
            if marker not in (pathlib.Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")):
                raise RuntimeError(f"LFCS reset: PID {pid} is not an owned {scenario} process")
            os.kill(pid, 15)
            for _ in range(40):
                try: os.kill(pid, 0)
                except ProcessLookupError: break
                time.sleep(0.05)
            else:
                os.kill(pid, 9)
        except (ValueError, ProcessLookupError, PermissionError, FileNotFoundError): pass
        p.unlink(missing_ok=True)

def start_namespace_http(sid, namespace, port, bind, directory):
    p = subprocess.Popen(
        ["ip", "netns", "exec", namespace, "python3", "-m", "http.server", str(port),
         "--bind", bind, "--directory", directory],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "LFCS_EXTENDED_PID": sid})
    write(str(RUN/f"extended-{sid}.pid"), str(p.pid)+"\n")
    url = f"http://{bind}:{port}/"
    for _ in range(200):
        if p.poll() is not None:
            raise RuntimeError(f"{sid} backend exited before becoming ready")
        probe = subprocess.run(
            ["ip", "netns", "exec", namespace, "curl", "-fsS", "--max-time", "1", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            return
        time.sleep(0.05)
    p.terminate()
    raise RuntimeError(f"{sid} backend did not become ready")

def repair_nginx_baseline_links():
    """Repair only the common, unambiguous misplaced relative-link form.

    A link such as sites-enabled/server.conf -> sites-available/server.conf is
    resolved relative to sites-enabled and is therefore dangling. Preserve the
    site's file and intent by pointing it at the same basename in the sibling
    sites-available directory. Other user configuration is left untouched.
    """
    enabled = pathlib.Path("/etc/nginx/sites-enabled")
    available = pathlib.Path("/etc/nginx/sites-available")
    if not enabled.exists(): return
    for link in enabled.iterdir():
        if not link.is_symlink(): continue
        if not link.exists():
            target = os.readlink(link)
            parts = pathlib.PurePosixPath(target).parts
            if len(parts) != 2 or parts[0] != "sites-available": continue
            intended = available / parts[1]
            if not intended.is_file(): continue
            link.unlink()
            link.symlink_to(intended)
        try: intended = link.resolve(strict=True)
        except (FileNotFoundError, RuntimeError): continue
        # Preserve and normalize the one legacy Day-1 site produced by an older
        # workbook example. Its quoted one-argument return is invalid nginx
        # syntax; the intended literal response unambiguously needs status 200.
        try: content = intended.read_text()
        except (OSError, UnicodeDecodeError): continue
        if re.search(r"^\s*listen\s+8091(?:\s+default_server)?\s*;", content, re.M):
            fixed = re.sub(r'^(\s*)return\s+"day1-ready"\s*;',
                           r'\1return 200 "day1-ready";', content, flags=re.M)
            if fixed != content: intended.write_text(fixed)

def iptables_rules(chain, namespace=None):
    argv = ["iptables", "-S", chain]
    if namespace: argv = ["ip", "netns", "exec", namespace, *argv]
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    if result.returncode != 0: return []
    rules = []
    for line in result.stdout.splitlines():
        try: tokens = shlex.split(line)
        except ValueError: continue
        if len(tokens) >= 3 and tokens[0] == "-A" and tokens[1] == chain:
            rules.append(tokens[2:])
    return rules

def rule_value(tokens, *options, default=None):
    for option in options:
        try: return tokens[tokens.index(option)+1]
        except (ValueError, IndexError): pass
    return default

def rule_network(tokens):
    raw = rule_value(tokens, "-s", "--source", default="0.0.0.0/0")
    try: return ipaddress.ip_network(raw, strict=False)
    except ValueError: return None

def tcp_port_rule(tokens, port, verdicts):
    target = rule_value(tokens, "-j", "--jump", "-g", "--goto")
    dport = rule_value(tokens, "--dport", "--destination-port")
    return target in verdicts and dport == str(port)

def dnat_forward_scope():
    """Inspect all reachable ACCEPT paths, independently of option order.

    A service-specific jump may supply constraints inherited by its child.
    Established/related-only rules support either state or conntrack syntax.
    """
    def positive_values(tokens, *options):
        return [tokens[i+1] for i, token in enumerate(tokens[:-1])
                if token in options and (i == 0 or tokens[i-1] != "!")]

    def visit(chain, inherited=(), seen=()):
        if chain in seen: return False
        for rule in iptables_rules(chain, "router1"):
            path = (*inherited, *rule)
            target = rule_value(rule, "-j", "--jump", "-g", "--goto")
            if target in {"DROP", "REJECT", "RETURN", "LOG", "NFLOG"}: continue
            if target != "ACCEPT":
                if target and not visit(target, path, (*seen, chain)): return False
                continue
            states = [set(value.split(",")) for value in positive_values(path, "--ctstate", "--state")]
            if any(value and value <= {"ESTABLISHED", "RELATED"} for value in states): continue
            proto = positive_values(path, "-p", "--protocol")
            dest = positive_values(path, "-d", "--destination")
            port = positive_values(path, "--dport", "--destination-port", "--dports")
            tcp = bool({"tcp", "6"}.intersection(proto))
            service = tcp and bool({"10.10.2.10", "10.10.2.10/32"}.intersection(dest)) and "8080" in port
            translated = (tcp and any("DNAT" in value and value <= {"DNAT", "ESTABLISHED", "RELATED"} for value in states)
                          and "8185" in positive_values(path, "--ctorigdstport"))
            if not (service or translated): return False
        return True
    return visit("FORWARD")

def sshfs_student_connection(source):
    """Tie the mounted sshfs daemon to its live SSH transport via its socket/pipe.

    Resolve SSH's effective user/host/key options, rather than inferring the
    remote user from the display source or the local FUSE owner alone.
    """
    if source not in {f"{prefix}{host}:/srv/lfcs/node2"
                      for prefix in ("", "student@")
                      for host in ("node2", "10.10.2.10")}:
        return False
    uid = int(out("id -u student"))
    peers = {}
    for line in out("ss -xHn").splitlines():
        match = re.search(r"\*\s+(\d+)\s+\*\s+(\d+)", line)
        if match:
            left, right = (f"socket:[{n}]" for n in match.groups())
            peers[left] = right
    connections = out("ss -Hntp state established")
    processes = []
    for proc in pathlib.Path("/proc").glob("[0-9]*"):
        try:
            args = proc.joinpath("cmdline").read_bytes().decode().strip("\0").split("\0")
            if not args or proc.stat().st_uid != uid: continue
            fds = {os.readlink(fd) for fd in (proc / "fd").iterdir()}
            processes.append((pathlib.Path(args[0]).name, args, fds, proc.name))
        except (OSError, UnicodeError): continue
    for name, args, fds, pid in processes:
        if name != "sshfs" or "/dev/fuse" not in fds or "/mnt/lfcs/remote" not in args or source not in args: continue
        links = {peers.get(fd, fd) for fd in fds if fd.startswith(("pipe:[", "socket:["))}
        for transport, argv, transport_fds, transport_pid in processes:
            if transport != "ssh" or not links.intersection(transport_fds): continue
            if not any(f"pid={transport_pid}," in line and re.search(r"\s10\.10\.2\.10:22\s", line)
                       for line in connections.splitlines()): continue
            result = subprocess.run(["sudo", "-u", "student", "ssh", "-G", *argv[1:]],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            config = {}
            for line in result.stdout.splitlines():
                key, _, value = line.partition(" ")
                config.setdefault(key, []).append(value)
            if (result.returncode == 0 and config.get("user") == ["student"]
                    and config.get("hostname") in (["node2"], ["10.10.2.10"])
                    and "/srv/lfcs/keys/exam" in config.get("identityfile", [])):
                return True
    return False


def ordered_port_exception(namespace, chain, port, allowed_networks,
                           rejected_address, require_broad_reject=False):
    rules = iptables_rules(chain, namespace)
    allowed = {ipaddress.ip_network(x) for x in allowed_networks}
    rejected_ip = ipaddress.ip_address(rejected_address)
    accepts = [(i, rule_network(r)) for i, r in enumerate(rules)
               if tcp_port_rule(r, port, {"ACCEPT"})]
    rejects = [(i, rule_network(r)) for i, r in enumerate(rules)
               if tcp_port_rule(r, port, {"DROP", "REJECT"})]
    all_accepts=accepts
    accepts = [(i, n) for i, n in all_accepts if n in allowed]
    rejects = [(i, n) for i, n in rejects if n and rejected_ip in n and
               (not require_broad_reject or n == ipaddress.ip_network("0.0.0.0/0"))]
    if not accepts or not rejects: return False
    # The exception must precede any reject that would also match its source.
    for ai, anet in accepts:
        conflicts = [ri for ri, rnet in rejects if next(iter(anet.hosts()), anet.network_address) in rnet]
        if not conflicts or ai >= min(conflicts):
            continue
        first_reject=min(conflicts)
        overbroad=[bi for bi,bnet in all_accepts
                   if bnet and bnet not in allowed and rejected_ip in bnet
                   and bi < first_reject]
        if not overbroad: return True
    return False

def nat_rule_packets(source="10.10.1.0/24", require_oif=True):
    total = 0
    rendered = out("ip netns exec router1 iptables-save -c -t nat")
    for raw in rendered.splitlines():
        if " -A POSTROUTING " not in raw: continue
        try: tokens = shlex.split(raw)
        except ValueError: continue
        if rule_value(tokens, "-j", "--jump") != "MASQUERADE": continue
        if rule_value(tokens, "-s", "--source") != source: continue
        if require_oif and rule_value(tokens, "-o", "--out-interface") != "eth0": continue
        match = re.match(r"^\[(\d+):(\d+)\]", raw)
        if match: total += int(match.group(1))
    return total

def observe_http_source(namespace, port):
    """Return (round-trip succeeded, receiver-observed peer address)."""
    peer = pathlib.Path(f"/run/lfcs-lab/nat-peer-{port}")
    ready = peer.with_suffix(".ready")
    peer.unlink(missing_ok=True)
    ready.unlink(missing_ok=True)
    code = r'''
import http.server, pathlib, socketserver, sys
peer=pathlib.Path(sys.argv[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        peer.write_text(self.client_address[0]+"\n")
        self.send_response(200); self.end_headers(); self.wfile.write(b"nat-ok\n")
    def log_message(self, *args): pass
class Server(http.server.HTTPServer):
    def server_bind(self):
        # This fixed lab endpoint needs no reverse DNS (which may be offline).
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address
s=Server(("10.10.0.2", int(sys.argv[2])), H)
pathlib.Path(sys.argv[3]).touch()
s.handle_request()
'''
    server = subprocess.Popen(
        [sys.executable, "-c", code, str(peer), str(port), str(ready)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 3
        while not ready.exists():
            if server.poll() is not None or time.monotonic() >= deadline:
                return False, ""
            time.sleep(0.02)
        request = subprocess.run(
            ["ip", "netns", "exec", namespace, "curl", "-fsS", "--max-time", "3",
             f"http://10.10.0.2:{port}/"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for _ in range(30):
            if peer.exists(): break
            time.sleep(0.05)
        observed = peer.read_text().strip() if peer.exists() else ""
        return request.returncode == 0 and request.stdout == "nat-ok\n", observed
    finally:
        if server.poll() is None:
            server.terminate()
            try: server.wait(timeout=1)
            except subprocess.TimeoutExpired: server.kill()
        peer.unlink(missing_ok=True)
        ready.unlink(missing_ok=True)

def functional_masquerade_probe():
    before = nat_rule_packets()
    positive_ok, translated = observe_http_source("node1", 18086)
    after = nat_rule_packets()
    negative_before = after
    negative_ok, untranslated = observe_http_source("node2", 18087)
    negative_after = nat_rule_packets()
    return {
        "positive": positive_ok and translated == "10.10.0.1" and after > before,
        "negative": negative_ok and untranslated == "10.10.2.10" and negative_after == negative_before,
    }

def saved_iptables_preserves_docker(path="/etc/iptables/rules.v4"):
    saved = pathlib.Path(path)
    if not saved.is_file(): return False
    text = saved.read_text(errors="replace")
    required = set()
    for table in ("filter", "nat"):
        rendered = out(f"iptables -t {table} -S")
        required.update(re.findall(r"^-N (DOCKER(?:-[A-Z0-9-]+)?)$", rendered, re.M))
    defined = set(re.findall(r"^:([A-Za-z0-9_-]+)\s", text, re.M))
    return bool(required) and required.issubset(defined)

def nginx_server_has(port, directive_pattern):
    rendered = run("nginx -T", check=False, capture=True)
    if rendered.returncode != 0: return False
    text = rendered.stdout
    for match in re.finditer(r"\bserver\s*\{", text):
        depth, end = 1, match.end()
        while end < len(text) and depth:
            if text[end] == "{": depth += 1
            elif text[end] == "}": depth -= 1
            end += 1
        if depth: continue
        block = text[match.start():end]
        if (re.search(rf"\blisten\s+(?:[^;\n]*:)?{port}(?:\s|;)", block) and
                re.search(directive_pattern, block)):
            return True
    return False

def systemd_config_last_value(name, setting):
    rendered = run(f"systemd-analyze cat-config {shlex.quote(name)}",
                   check=False, capture=True)
    if rendered.returncode != 0: return None
    value = None
    pattern = re.compile(rf"^{re.escape(setting)}=(.*)$")
    for raw in rendered.stdout.splitlines():
        match = pattern.match(raw.strip())
        if match: value = match.group(1).strip()
    return value

def clean_systemd_fixtures(sid=None):
    command = "reset-all" if sid is None else f"reset {shlex.quote(sid)}"
    run(f"/usr/local/lib/lfcs/systemd-ownership.py {command}")

def clean_cron_fixtures():
    for f in ["/etc/cron.d/alder-backup","/etc/cron.d/maple-prune"]:
        pathlib.Path(f).unlink(missing_ok=True)
    run("crontab -u student -r", check=False, capture=True)
    p = pathlib.Path("/etc/anacrontab")
    if p.exists():
        p.write_text("\n".join(x for x in p.read_text().splitlines() if "cedar-index" not in x)+"\n")

def clean_docker_fixtures():
    for c in ("web-fern","web-ivy"):
        run(f"docker rm -f {c}", check=False, capture=True)

def clean_firewall_fixtures():
    for ns in ("node1","node2","node3","router1"):
        net(ns, "iptables -F; iptables -t nat -F; iptables -X; iptables -t nat -X; iptables -P INPUT ACCEPT; iptables -P OUTPUT ACCEPT; iptables -P FORWARD ACCEPT", False)
    run("iptables -D INPUT -j LFCS_PERSIST 2>/dev/null; iptables -F LFCS_PERSIST 2>/dev/null; iptables -X LFCS_PERSIST 2>/dev/null", check=False)

def clean_mount_fixtures():
    """Detach scenario mounts before systemd generators inspect fstab.

    A solved hard NFS mount can make daemon-reload wedge if systemd ownership
    cleanup runs first.  Lazy detach is intentional here: reset-all subsequently
    stops the owned services and rebuilds all storage/runtime state.
    """
    fstab = pathlib.Path("/etc/fstab")
    if fstab.exists():
        fstab.write_text("\n".join(
            line for line in fstab.read_text().splitlines()
            if "LFCS-EXT" not in line and "LFCS-LAB" not in line
        ) + "\n")
    unmount_nfs_client_contexts()
    run("/usr/local/lib/lfcs/nbd-ownership.py teardown")
    run("fusermount3 -uz /mnt/lfcs/remote", check=False, capture=True)
    run("fusermount3 -uz /mnt/lfcs/sshfs", check=False, capture=True)
    for mountpoint in (
            "/mnt/lfcs/on-demand/projects", "/mnt/lfcs/projects",
            "/mnt/lfcs/amber", "/mnt/lfcs/archive", "/mnt/lfcs/noexec",
            "/mnt/lfcs/recovery", "/mnt/lfcs/remote", "/mnt/lfcs/sshfs",
            "/mnt/lfcs/nbd"):
        run(f"timeout 5s umount -l {shlex.quote(mountpoint)}",
            check=False, capture=True)
    units = " ".join(
        out(f"systemd-escape --path --suffix=mount {shlex.quote(mountpoint)}")
        for mountpoint in (
            "/mnt/lfcs/on-demand/projects", "/mnt/lfcs/projects",
            "/mnt/lfcs/amber", "/mnt/lfcs/archive", "/mnt/lfcs/noexec",
            "/mnt/lfcs/recovery", "/mnt/lfcs/remote", "/mnt/lfcs/sshfs",
            "/mnt/lfcs/nbd")
    )
    run(f"systemctl reset-failed {units}", check=False, capture=True)

def clean_nginx_fixtures():
    stop_owned_processes(("nginx-",))
    run("/usr/local/lib/lfcs/nginx-ownership.py reset-all", check=False)

def clean_virtualization_fixtures():
    for pth in ["/tmp/virt-list","/tmp/virt-dominfo","/tmp/exam-maple-info"]:
        pathlib.Path(pth).unlink(missing_ok=True)
    shutil.rmtree("/srv/lfcs/virt", ignore_errors=True)

def clean_common():
    stop_owned_processes()
    clean_mount_fixtures()
    clean_systemd_fixtures()
    clean_cron_fixtures()
    clean_docker_fixtures()
    clean_firewall_fixtures()
    clean_nginx_fixtures()
    clean_virtualization_fixtures()
    pathlib.Path("/etc/iptables/rules.v4").unlink(missing_ok=True)
    pathlib.Path("/etc/iptables/lfcs-router.v4").unlink(missing_ok=True)
    pathlib.Path("/tmp/deployer-banner").unlink(missing_ok=True)

def reset_one(sid):
    # Each family owns distinct names. Storage scenarios exclusively own the three
    # practice disks and therefore invoke the existing safe disk reset helper.
    if sid.startswith(("sysinfo-","process-")):
        for p in pathlib.Path("/tmp").glob("*report"):
            if p.name in {"walnut-report","boot-clock-report"}: p.unlink(missing_ok=True)
        for p in ("/tmp/kernel-release","/tmp/overcommit-value","/tmp/default-target"):
            pathlib.Path(p).unlink(missing_ok=True)
        stop_owned_processes()
    elif sid.startswith("systemd-"):
        clean_systemd_fixtures(sid)
    elif sid.startswith("cron-"):
        clean_cron_fixtures()
    elif sid == "source-01":
        shutil.rmtree("/usr/local/src/leafutil", ignore_errors=True)
        pathlib.Path("/usr/bin/leafutil").unlink(missing_ok=True)
    elif sid.startswith("docker-"):
        for c in ("web-fern","web-ivy"): run(f"docker rm -f {c}",check=False,capture=True)
        shutil.rmtree("/srv/lfcs/fern",ignore_errors=True); shutil.rmtree("/srv/lfcs/ivy",ignore_errors=True)
        pathlib.Path("/tmp/web-fern-report").unlink(missing_ok=True)
    elif sid.startswith("timesync-"):
        pathlib.Path("/etc/systemd/timesyncd.conf.d/95-lfcs-broken.conf").unlink(missing_ok=True)
        pathlib.Path("/etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf").unlink(missing_ok=True)
        restore_timesync_baseline()
        run("systemctl reset-failed systemd-timesyncd; systemctl enable systemd-timesyncd; systemctl restart systemd-timesyncd",check=False)
    elif sid.startswith("virt-"):
        shutil.rmtree("/srv/lfcs/virt",ignore_errors=True)
        for p in ("/tmp/virt-list","/tmp/virt-dominfo","/tmp/exam-maple-info"): pathlib.Path(p).unlink(missing_ok=True)
    elif sid.startswith("nmcli-"):
        for name in ("lfcs-cedar", "lfcs-aspen", "lfcs-maple", "lfcs-maple-old"):
            run(f"nmcli connection delete {name}", check=False, capture=True)
        for device in ("nmcedar0", "nmaspen0", "nmaple0"):
            run(f"ip link delete {device}", check=False, capture=True)
    elif sid.startswith("iptables-"):
        stop_owned_processes((sid,))
        clean_firewall_fixtures()
        if sid == "iptables-04":
            shutil.rmtree("/srv/lfcs/redirect-8084", ignore_errors=True)
        pathlib.Path("/etc/iptables/rules.v4").unlink(missing_ok=True)
        pathlib.Path("/etc/iptables/lfcs-router.v4").unlink(missing_ok=True)
    elif sid.startswith("nginx-"):
        stop_owned_processes(("nginx-",))
        run(f"/usr/local/lib/lfcs/nginx-ownership.py reset {shlex.quote(sid)}")
    elif sid.startswith("ssh-match-"):
        run(f"/usr/local/lib/lfcs/ssh-ownership.py reset {shlex.quote(sid)}")
        pathlib.Path("/etc/lfcs-lab/sshd-match.conf").unlink(missing_ok=True)
        pathlib.Path("/tmp/deployer-banner").unlink(missing_ok=True)
        for u in ("buildbot","deployer"): run(f"userdel -r {u}",check=False,capture=True)
        run("groupdel sftp-only",check=False,capture=True)
    elif sid.startswith(("lvm-","mount-","nfs-","sshfs-","nbd-","autofs-","swap-")):
        if sid == "sshfs-01":
            run("/usr/local/lib/lfcs/ssh-ownership.py reset sshfs-01")
        if sid == "autofs-01":
            run("systemctl disable --now autofs; systemctl reset-failed autofs",check=False,capture=True)
        # Remove lab-owned persistence before any mount operation. In particular,
        # an NFS mount created through a network namespace may be unreachable from
        # the default namespace during cleanup; it must not be retried by mount -a.
        for marker in ("LFCS-EXT","LFCS-LAB"):
            p=pathlib.Path("/etc/fstab")
            if p.exists(): p.write_text("\n".join(x for x in p.read_text().splitlines() if marker not in x)+"\n")
        unmount_nfs_client_contexts()
        run("/usr/local/lib/lfcs/nbd-ownership.py teardown")
        run("fusermount3 -u /mnt/lfcs/remote",check=False,capture=True)
        mounts = ["/mnt/lfcs/projects","/mnt/lfcs/amber","/mnt/lfcs/archive","/mnt/lfcs/noexec","/mnt/lfcs/recovery"]
        if sid == "autofs-01":
            mounts.append("/mnt/lfcs/on-demand/projects")
        for m in mounts:
            run(f"timeout 5s umount -l {m}",check=False,capture=True)
        run("swapoff /var/lib/lfcs-lab/exam.swap",check=False,capture=True)
        pathlib.Path("/var/lib/lfcs-lab/exam.swap").unlink(missing_ok=True)
        if sid == "autofs-01":
            pathlib.Path("/etc/auto.master.d/lfcs-ext.autofs").unlink(missing_ok=True)
            pathlib.Path("/etc/auto.lfcs-projects").unlink(missing_ok=True)
            remove_autofs_entries("/mnt/lfcs/on-demand", "/srv/lfcs/projects")
        stop_owned_processes()
        run("/usr/local/lib/lfcs/storage.sh reset-all")
        if sid in {"nfs-01", "autofs-01"}:
            # Remove learner answers from any supported exports file, not just
            # the starter file. Also clear advanced-09's deliberately misspelled
            # fixture so exportfs can validate the independent scenario.
            remove_export_path("/srv/lfcs/projects")
            remove_export_path("/srv/lfcs/shrae")
            pathlib.Path("/etc/exports.d/lfcs-ext-projects.exports").unlink(missing_ok=True)
            for grade_artifact in pathlib.Path("/srv/lfcs/projects").glob(".lfcs-grade-*"):
                grade_artifact.unlink(missing_ok=True)
            try:
                pathlib.Path("/etc/exports.d").rmdir()
            except OSError:
                pass
            run("exportfs -ra",check=False,capture=True)
        if sid in {"nfs-01", "autofs-01"}:
            run("systemctl disable --now nfs-server", check=False, capture=True)
    elif sid.startswith(("find-","text-","archive-","redirection-","links-","permissions-","attributes-","git-")):
        run("chattr -a -i /srv/lfcs/ledger/*",check=False,capture=True)
        for p in ("/srv/lfcs/find","/srv/lfcs/quarantine","/srv/lfcs/markers","/srv/lfcs/app","/srv/lfcs/archives","/srv/lfcs/links","/srv/lfcs/shared","/srv/lfcs/bin","/srv/lfcs/ledger","/srv/lfcs/git"):
            shutil.rmtree(p,ignore_errors=True)
        for pattern in ("/tmp/hazel-large","/tmp/window","/tmp/bundle-selected"):
            shutil.rmtree(pattern,ignore_errors=True)
        for p in pathlib.Path("/tmp").glob("*"):
            if p.name in {"recent-configs","image-list","suid-audit","staging-count","5xx-by-ip","mobile-errors","config-drift","error-window","team-names","common-members","records.tar.xz","stream.out","stream.err","stream.status","stream-combined","stdout-count","pipeline.err","producer.status","ledger-attributes","selected-branch"}: p.unlink(missing_ok=True)
        for u in ("hazel",): run(f"userdel -r {u}",check=False,capture=True)
        for g in ("cacheops","editors","auditors"): run(f"groupdel {g}",check=False,capture=True)
    elif sid.startswith(("usermod-","sudo-","env-","limits-")):
        for name in ("91-lfcs-maren", "92-lfcs-deployops", "93-lfcs-monitor", "94-lfcs-backupbot"):
            pathlib.Path("/etc/sudoers.d", name).unlink(missing_ok=True)
        for f in pathlib.Path("/etc/security/limits.d").glob("9*-lfcs*.conf"): f.unlink(missing_ok=True)
        for f in pathlib.Path("/etc/profile.d").glob("*lfcs-ext*"): f.unlink(missing_ok=True)
        for u in ("maren","devin","rhea","tempwriter","rowan","sampleleaf","backupbot","release","archive"):
            run(f"userdel -r {u}",check=False,capture=True)
        for g in ("maren","devin","rhea","tempwriter","rowan","sampleleaf","backupbot","release","archive","platform","incident","analytics","authors","deployops","monitoring","batch"):
            run(f"groupdel {g}",check=False,capture=True)
        p=pathlib.Path("/etc/skel/.profile")
        if p.exists(): p.write_text("\n".join(x for x in p.read_text().splitlines() if x not in {"export EDITOR=vim","umask 027"})+"\n")
        restore_student_admin()

def setup_operations(sid):
    if sid == "sysinfo-01": return
    if sid == "sysinfo-02": return
    if sid == "systemd-04":
        run("useradd -r -s /usr/sbin/nologin svc-alder",check=False)
        write("/run/alder-user", "", owner="svc-alder:svc-alder")
        write("/usr/local/bin/alder-worker","#!/bin/sh\necho $(id -un) >/run/alder-user\nexec sleep infinity\n",0o755)
        service("alder-worker","""[Unit]\nDescription=Alder worker\n[Service]\nUser=missing-alder\nExecStart=/usr/local/bin/alder-worker\n[Install]\nWantedBy=multi-user.target\n""")
        run("systemctl start alder-worker",check=False)
    elif sid == "systemd-05":
        write("/usr/local/bin/pine-api","#!/bin/sh\necho ${APP_MODE:-missing} >/run/pine-mode\nexec sleep infinity\n",0o755)
        service("pine-api","""[Unit]\nDescription=Pine API\n[Service]\nExecStart=/usr/local/bin/pine-api\n[Install]\nWantedBy=multi-user.target\n""")
        run("systemctl enable --now pine-api")
    elif sid == "systemd-06":
        write("/usr/local/bin/juniper-agent","#!/bin/sh\ntouch /run/juniper-ready\nexec sleep infinity\n",0o755)
        service("juniper-agent","""[Unit]\nDescription=Juniper agent\n[Service]\nExecStart=/usr/local/bin/juniper-agent\nRestart=no\n[Install]\nWantedBy=multi-user.target\n""")
        run("systemctl mask --runtime juniper-agent")
    elif sid == "systemd-07":
        write("/usr/local/bin/spruce-data","#!/bin/sh\ntouch /run/spruce-data-ready\nexec sleep infinity\n",0o755)
        write("/usr/local/bin/spruce-web","#!/bin/sh\ntest -f /run/spruce-data-ready || exit 3\ntouch /run/spruce-web-ready\nexec sleep infinity\n",0o755)
        service("spruce-data","[Unit]\nDescription=Spruce data\n[Service]\nExecStart=/usr/local/bin/spruce-data\n[Install]\nWantedBy=multi-user.target\n")
        service("spruce-web","[Unit]\nDescription=Spruce web\n[Service]\nExecStart=/usr/local/bin/spruce-web\n[Install]\nWantedBy=multi-user.target\n")
    elif sid == "systemd-08":
        write("/etc/lfcs-lab/hemlock.env","HEMLOCK_COLOR=green\n")
        write("/usr/local/bin/hemlock-job","#!/bin/sh\ntest \"${HEMLOCK_COLOR:-}\" = green || exit 4\necho \"$HEMLOCK_COLOR\" >/run/hemlock-result\nexec sleep infinity\n",0o755)
        service("hemlock-job","[Unit]\nDescription=Hemlock job\n[Service]\nEnvironmentFile=/etc/lfcs-lab/missing.env\nExecStart=/usr/local/bin/hemlock-job\nRestart=no\n[Install]\nWantedBy=multi-user.target\n")
        run("systemctl start hemlock-job",check=False)
    elif sid == "cron-02":
        write("/usr/local/bin/alder-backup","#!/bin/sh\ntouch /tmp/alder-backup-ran\n",0o755)
        write("/etc/cron.d/alder-backup","15 7 * * 1,3,5 student /usr/local/bin/alder-backup --incremental\n",0o644)
    elif sid == "cron-03":
        write("/usr/local/bin/maple-prune","#!/bin/sh\nexit 0\n",0o755)
        write("/etc/cron.d/maple-prune","40 2 1 * /usr/local/bin/maple-prune\n",0o666)
    elif sid == "cron-04":
        write("/usr/local/bin/cedar-index","#!/bin/sh\ntouch /tmp/cedar-index-ran\n",0o755)
    elif sid == "process-02":
        pathlib.Path("/srv/lfcs/process").mkdir(parents=True,exist_ok=True)
        write("/srv/lfcs/process/walnut.data","active\n")
        p=subprocess.Popen(["bash","-c","exec 7</srv/lfcs/process/walnut.data; exec -a walnut-worker env LFCS_ROLE=walnut sleep 10000"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,env={**os.environ,"LFCS_EXTENDED_PID":"walnut"})
        write(str(RUN/"extended-walnut.pid"),str(p.pid)+"\n")
    elif sid == "source-01":
        root=pathlib.Path("/usr/local/src/leafutil"); root.mkdir(parents=True,exist_ok=True)
        write(root/"leafutil.in","#!/bin/sh\necho 'prefix=@PREFIX@ ipv6=@IPV6@'\n")
        write(root/"configure","""#!/bin/sh
prefix=/usr/local; ipv6=enabled
for arg in "$@"; do case "$arg" in --prefix=*) prefix=${arg#*=};; --disable-ipv6) ipv6=disabled;; *) echo "unknown option: $arg" >&2; exit 2;; esac; done
sed "s|@PREFIX@|$prefix|;s|@IPV6@|$ipv6|" leafutil.in > leafutil
cat > Makefile <<EOF
all:\n\t@test -x leafutil || chmod +x leafutil
install:\n\tinstall -D -m 0755 leafutil \\$(DESTDIR)$prefix/bin/leafutil
EOF
printf 'prefix=%s\nipv6=%s\n' "$prefix" "$ipv6" > config.status
chmod +x leafutil
""",0o755)
    elif sid.startswith("docker-"):
        root=pathlib.Path("/srv/lfcs/fern" if sid=="docker-01" else "/srv/lfcs/ivy"); root.mkdir(parents=True,exist_ok=True)
        write(root/"index.html",("fern-ready\n" if sid=="docker-01" else "ivy-ready\n"))
        if sid=="docker-01": run("docker run -d --name web-fern -p 8131:80 -e LFCS_STAGE=practice -v /srv/lfcs/fern:/usr/share/nginx/html:ro nginx:alpine")
        else: run("docker run -d --name web-ivy -p 8999:80 -v /srv/lfcs/fern:/usr/share/nginx/html nginx:alpine")
    elif sid.startswith("timesync-"):
        if sid=="timesync-01": write("/etc/systemd/timesyncd.conf.d/95-lfcs-broken.conf","[Time]\nNTP=invalid.lfcs.invalid\nPollIntervalMinSec=8\n")
        else: write("/etc/systemd/timesyncd.conf.d/95-lfcs-broken.conf","[Time]\nNTP=invalid.lfcs.invalid\nConnectionRetrySec=5\n")
        run("systemctl reset-failed systemd-timesyncd; systemctl enable systemd-timesyncd; systemctl restart systemd-timesyncd",check=False)
    elif sid.startswith("virt-"):
        v=pathlib.Path("/srv/lfcs/virt"); v.mkdir(parents=True,exist_ok=True)
        if sid=="virt-03": write(v/"lifecycle.sh","#!/bin/bash\nURI=test:///default\n# Complete the lifecycle operations for exam-elm.\n",0o755)
        elif sid=="virt-04":
            run("qemu-img create -f qcow2 /srv/lfcs/virt/exam-ash.qcow2 64M >/dev/null")
            write(v/"exam-ash.xml","<domain type='test'><name>exam-ash</name><memory unit='MiB'>256</memory><vcpu>1</vcpu></domain>\n")
        elif sid=="virt-05":
            run("qemu-img create -f qcow2 /srv/lfcs/virt/exam-oak.qcow2 64M >/dev/null")
            write(v/"exam-oak.xml","""<domain type='test'><name>exam-oak</name><uuid>11111111-2222-3333-4444-555555555555</uuid><memory unit='MiB'>512</memory><vcpu>1</vcpu><metadata><autostart>disabled</autostart></metadata><devices><disk type='file'><source file='/srv/lfcs/virt/exam-oak.qcow2'/><target dev='vda'/></disk><interface type='network'><source network='default'/></interface></devices></domain>\n""")
        elif sid=="virt-06": run("qemu-img create -f qcow2 /srv/lfcs/virt/exam-maple.qcow2 64M >/dev/null")
        elif sid=="virt-07": run("qemu-img create -f qcow2 /srv/lfcs/virt/exam-willow.qcow2 48M >/dev/null")
        elif sid in {"virt-08","virt-09"}:
            name="birch" if sid=="virt-08" else "cedar"; run(f"qemu-img create -f qcow2 /srv/lfcs/virt/exam-{name}.qcow2 64M >/dev/null")
            if sid=="virt-08": write(v/"create-birch.sh","#!/bin/bash\n# Construct the virt-install command. Do not run it.\n",0o755)
            else: write(v/"create-cedar.sh","#!/bin/bash\nvirt-install --name wrong --memory 256 --vcpus 4 --disk /srv/lfcs/virt/missing.raw --graphics vnc\n",0o755)

def setup_network(sid):
    if sid == "nmcli-01":
        run("nmcli connection add type dummy ifname nmcedar0 con-name lfcs-cedar "
            "connection.uuid 00000000-0000-4000-8000-000000000101 "
            "ipv4.method manual ipv4.addresses 198.51.100.99/24 "
            "ipv4.never-default no ipv6.method disabled")
    elif sid == "nmcli-02":
        run("nmcli connection add type dummy ifname nmaspen0 con-name lfcs-aspen "
            "connection.uuid 00000000-0000-4000-8000-000000000102 "
            "ipv4.method manual ipv4.addresses 192.0.2.20/24 "
            "ipv4.never-default yes ipv6.method disabled")
        run("nmcli connection up lfcs-aspen")
    elif sid == "nmcli-03":
        # A veth presents as Ethernet and safely supports two saved profiles.
        # NetworkManager 1.46 crashes when two dummy-type profiles claim the
        # same generated dummy device, so avoid that upstream edge case.
        run("ip link add nmaple0 type veth peer name nmaple-peer0")
        run("nmcli device set nmaple0 managed yes")
        run("nmcli connection add type ethernet ifname nmaple0 con-name lfcs-maple "
            "connection.uuid 00000000-0000-4000-8000-000000000103 "
            "ipv4.method manual ipv4.addresses 203.0.113.30/24 "
            "ipv4.never-default no connection.autoconnect no ipv6.method disabled")
        run("nmcli connection add type ethernet ifname nmaple0 con-name lfcs-maple-old "
            "connection.uuid 00000000-0000-4000-8000-000000000104 "
            "ipv4.method manual ipv4.addresses 203.0.113.99/24 "
            "ipv4.never-default yes connection.autoconnect yes ipv6.method disabled")
        run("nmcli connection up lfcs-maple-old ifname nmaple0")
    elif sid.startswith("iptables-"):
        target="router1" if sid in {"iptables-05","iptables-06","iptables-07","iptables-10"} else ("node1" if sid=="iptables-03" else "node2")
        net(target,"iptables -F; iptables -t nat -F; iptables -X; iptables -t nat -X; iptables -P INPUT ACCEPT; iptables -P OUTPUT ACCEPT; iptables -P FORWARD ACCEPT")
        if sid in {"iptables-01","iptables-02","iptables-08"}:
            port={"iptables-01":9121,"iptables-02":9122,"iptables-08":9128}[sid]
            start_namespace_http(sid, "node2", port, "0.0.0.0", "/srv/lfcs/node2")
            if sid=="iptables-08": net("node2","iptables -A INPUT -p tcp --dport 9128 -j REJECT")
        elif sid in {"iptables-03","iptables-07","iptables-10"}:
            port={"iptables-03":9123,"iptables-07":9127,"iptables-10":9130}[sid]
            start_namespace_http(sid, "node3", port, "0.0.0.0", "/srv/lfcs/node3")
            if sid in {"iptables-07","iptables-10"}: net("router1","iptables -P FORWARD DROP")
        elif sid=="iptables-04":
            pathlib.Path("/srv/lfcs/redirect-8084").mkdir(parents=True, exist_ok=True)
            write("/srv/lfcs/redirect-8084/index.html", "node2-ready\n")
            start_namespace_http(sid, "node2", 8084, "127.0.0.1", "/srv/lfcs/redirect-8084")
        elif sid=="iptables-09":
            run("iptables -N LFCS_PERSIST; iptables -A INPUT -j LFCS_PERSIST; iptables -A LFCS_PERSIST -p tcp --dport 8139 -j REJECT")
    elif sid.startswith("nginx-"):
        run("systemctl enable --now nginx")
        if sid=="nginx-02":
            pathlib.Path("/srv/lfcs/alder").mkdir(parents=True,exist_ok=True); write("/srv/lfcs/alder/index.html","alder-ready\n")
            write("/etc/nginx/sites-available/lfcs-ext-alder","server { listen 8112 root /srv/lfcs/missing location / { try_files $uri =404; } }\n")
        elif sid=="nginx-06":
            pathlib.Path("/etc/lfcs/tls/fern").mkdir(parents=True,exist_ok=True)
            run("openssl req -x509 -newkey rsa:2048 -nodes -subj /CN=fern.lfcs.internal -days 30 -keyout /etc/lfcs/tls/fern/server.key -out /etc/lfcs/tls/fern/server.crt >/dev/null 2>&1")
            pathlib.Path("/etc/lfcs/tls/fern/server.key").chmod(0o644)
            write("/etc/nginx/sites-available/lfcs-ext-fern","server { listen 8446 ssl; ssl_certificate /etc/lfcs/tls/fern/server.crt; ssl_certificate_key /etc/lfcs/tls/fern/missing.key; location / { return 200 'fern-secure\\n'; } }\n")
    elif sid.startswith("ssh-match-"):
        run("groupadd -f sftp-only")
        for u in ("buildbot","deployer"): run(f"id {u} >/dev/null 2>&1 || useradd -m {u}")
        base="""Port 2229
ListenAddress 127.0.0.1
HostKey /etc/ssh/ssh_host_ed25519_key
UsePAM no
PasswordAuthentication yes
PubkeyAuthentication yes
X11Forwarding yes
PermitRootLogin yes
Subsystem sftp internal-sftp
"""
        if sid=="ssh-match-01": base += "Match User buildbot\n    PasswordAuthentication yes\n    PubkeyAuthentication no\n"
        elif sid=="ssh-match-02":
            run("usermod -aG sftp-only buildbot")
            base += "Match Group sftp-only\n    X11Forwarding yes\n"
        else: base += "Match User deployer\n    Banner /etc/missing-banner\n    PermitRootLogin yes\n"
        write("/etc/lfcs-lab/sshd-match.conf",base)

def setup_one(sid):
    reset_one(sid)
    if sid.startswith("nginx-"):
        run(f"/usr/local/lib/lfcs/nginx-ownership.py capture {shlex.quote(sid)}")
    if sid.startswith("ssh-match-") or sid == "sshfs-01":
        run(f"/usr/local/lib/lfcs/ssh-ownership.py capture {shlex.quote(sid)}")
    if sid.startswith(("sysinfo-","systemd-","cron-","process-","source-","docker-","timesync-","virt-")): setup_operations(sid)
    elif sid.startswith(("nmcli-","iptables-","nginx-","ssh-match-")): setup_network(sid)
    elif sid.startswith(("lvm-","mount-","nfs-","sshfs-","nbd-","autofs-","swap-")): setup_storage(sid)
    elif sid.startswith(("find-","text-","archive-","redirection-","links-","permissions-","attributes-","git-")): setup_commands(sid)
    elif sid.startswith(("usermod-","sudo-","env-","limits-")): setup_users(sid)

def setup_storage(sid):
    if sid.startswith("lvm-"):
        if sid=="lvm-01":
            run("pvcreate -ff -y /dev/lfcs-disk1 /dev/lfcs-disk2 /dev/lfcs-disk3 >/dev/null; vgcreate orchard /dev/lfcs-disk1 /dev/lfcs-disk2 /dev/lfcs-disk3 >/dev/null; lvcreate -L 120M -n harvest orchard /dev/lfcs-disk2 >/dev/null; mkfs.ext4 -F /dev/orchard/harvest >/dev/null; mkdir -p /mnt/lfcs/orchard; mount /dev/orchard/harvest /mnt/lfcs/orchard; echo preserve-orchard >/mnt/lfcs/orchard/sentinel")
        elif sid=="lvm-02":
            run("pvcreate -ff -y /dev/lfcs-disk1 /dev/lfcs-disk2 >/dev/null; vgcreate oldfruit /dev/lfcs-disk1 /dev/lfcs-disk2 >/dev/null; lvcreate -L 96M -n legacy oldfruit /dev/lfcs-disk1 >/dev/null")
        elif sid=="lvm-03":
            run("pvcreate -ff -y /dev/lfcs-disk1 >/dev/null; vgcreate garden /dev/lfcs-disk1 >/dev/null; lvcreate -L 128M -n data garden >/dev/null; mkfs.ext4 -F /dev/garden/data >/dev/null; mkdir -p /mnt/lfcs/garden; mount /dev/garden/data /mnt/lfcs/garden; echo garden-safe >/mnt/lfcs/garden/sentinel")
        elif sid=="lvm-04":
            run("pvcreate -ff -y /dev/lfcs-disk1 >/dev/null; vgcreate observatory /dev/lfcs-disk1 >/dev/null; lvcreate -L 320M -n logs observatory >/dev/null; mkfs.xfs -f /dev/observatory/logs >/dev/null; mkdir -p /mnt/lfcs/observatory; mount /dev/observatory/logs /mnt/lfcs/observatory; echo stars-safe >/mnt/lfcs/observatory/sentinel")
    elif sid.startswith("mount-"):
        run("mkfs.ext4 -F -L LFCS_EXT /dev/lfcs-disk1 >/dev/null")
        if sid=="mount-01":
            run("mkdir -p /mnt/lfcs/noexec; mount /dev/lfcs-disk1 /mnt/lfcs/noexec; printf '#!/bin/sh\\necho should-not-run\\n' >/mnt/lfcs/noexec/check.sh; chmod 0755 /mnt/lfcs/noexec/check.sh")
        elif sid=="mount-02":
            run("mkdir -p /mnt/lfcs/archive; mount /dev/lfcs-disk1 /mnt/lfcs/archive; echo archive-safe >/mnt/lfcs/archive/sentinel")
        else:
            run("mkdir -p /mnt/lfcs/recovery")
            with pathlib.Path("/etc/fstab").open("a") as f: f.write("UUID=00000000-1111-2222-3333-444444444444 /mnt/lfcs/recovery xfs defaults 0 2 # LFCS-LAB\n")
    elif sid=="nfs-01":
        pathlib.Path("/srv/lfcs/projects").mkdir(parents=True,exist_ok=True); write("/srv/lfcs/projects/README","projects-ready\n")
        shutil.chown("/srv/lfcs/projects", "student", "student")
        write("/etc/exports.d/lfcs-ext-projects.exports","/srv/lfcs/projects 10.10.1.0/24(rw,sync,no_subtree_check,insecure)\n")
        run("systemctl enable --now nfs-server; exportfs -ra")
        pathlib.Path("/mnt/lfcs/projects").mkdir(parents=True,exist_ok=True)
    elif sid=="sshfs-01":
        run("/usr/local/lib/lfcs/scenario-engine.sh setup advanced-10")
        run("/usr/local/lib/lfcs/ssh-ownership.py abandon advanced-10")
        pathlib.Path("/mnt/lfcs/remote").mkdir(parents=True,exist_ok=True); shutil.chown("/mnt/lfcs/remote","student","student")
        pathlib.Path("/srv/lfcs/keys/exam").chmod(0o600); shutil.chown("/srv/lfcs/keys/exam","student","student")
    elif sid=="nbd-01":
        run("modprobe nbd max_part=8")
        run("truncate -s 64M /var/lib/lfcs-disks/amber.img")
        shutil.chown("/var/lib/lfcs-disks/amber.img", "nbd", "nbd")
        nbd_config = pathlib.Path("/etc/nbd-server/config")
        config_text = nbd_config.read_text()
        if not re.search(r"(?m)^\s*allowlist\s*=", config_text):
            nbd_config.write_text(config_text.replace("[generic]\n", "[generic]\n    allowlist = true\n", 1))
        write("/etc/nbd-server/conf.d/amber.conf", """
            [amber]
                exportname = /var/lib/lfcs-disks/amber.img
                readonly = false
        """, 0o644, "root:root")
        pathlib.Path("/mnt/lfcs/amber").mkdir(parents=True,exist_ok=True)
    elif sid=="autofs-01":
        pathlib.Path("/srv/lfcs/projects").mkdir(parents=True,exist_ok=True); write("/srv/lfcs/projects/README","projects-ready\n")
        write("/etc/exports.d/lfcs-ext-projects.exports","/srv/lfcs/projects 127.0.0.1(rw,sync,no_subtree_check,insecure)\n")
        run("exportfs -ra; systemctl enable --now nfs-server autofs")
        pathlib.Path("/mnt/lfcs/on-demand").mkdir(parents=True,exist_ok=True)

def setup_find_data():
    run("groupadd -f cacheops; id hazel >/dev/null 2>&1 || useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m hazel")
    root=pathlib.Path("/srv/lfcs/find")
    for d in ("owner","perm","cache","media/archive","media/live","bin","inbox","staging"):(root/d).mkdir(parents=True,exist_ok=True)
    for name,size,owner in (("owner/large-a",16384,"hazel"),("owner/small",4096,"hazel"),("owner/root-large",20000,"root")):
        p=root/name; p.write_bytes(b"x"*size); shutil.chown(p,owner,owner)
    for name,mode in (("perm/exact-a",0o640),("perm/exact-b",0o640),("perm/other",0o644)):
        write(root/name,name+"\n",mode)
    for name in ("cache/old.tmp","cache/new.tmp","cache/foreign.tmp"):
        write(root/name,"x\n"); shutil.chown(root/name,"root","cacheops" if name!="cache/foreign.tmp" else "root")
    old=time.time()-7200; new=time.time()-300
    os.utime(root/"cache/old.tmp",(old,old)); os.utime(root/"cache/new.tmp",(new,new)); os.utime(root/"cache/foreign.tmp",(old,old))
    for name in ("media/live/A.JPG","media/live/b.png","media/live/c.gif","media/archive/old.png"): write(root/name,"image\n")
    for name,mode in (("bin/helper",0o4755),("bin/plain",0o755),("bin/data",0o4644)): write(root/name,"#!/bin/sh\n",mode)
    markers=pathlib.Path("/srv/lfcs/markers"); markers.mkdir(parents=True,exist_ok=True)
    write(markers/"start","s\n"); write(markers/"end","e\n"); now=time.time(); os.utime(markers/"start",(now-3600,now-3600)); os.utime(markers/"end",(now-1200,now-1200))
    for name,age in (("before",5000),("inside-a",2400),("inside-b",1800),("after",300)):
        write(root/("inbox/"+name),name+"\n"); os.utime(root/("inbox/"+name),(now-age,now-age))
    write(root/"staging/empty-a",""); write(root/"staging/empty-b",""); write(root/"staging/data","x\n"); (root/"staging/empty-dir").mkdir()
    for name,date in (("recent.conf","202608210101"),("old.conf","202608010101"),("recent.txt","202608220101")):
        write(root/name,"x\n"); run(f"touch -t {date} {shlex.quote(str(root/name))}")

def setup_commands(sid):
    if sid.startswith("find-"): setup_find_data()
    elif sid.startswith("text-"):
        pathlib.Path("/var/log/lfcs").mkdir(parents=True,exist_ok=True); pathlib.Path("/srv/lfcs/app").mkdir(parents=True,exist_ok=True)
        write("/var/log/lfcs/access.log","""10.1.1.1 GET / 500
10.1.1.2 GET /a 200
10.1.1.1 POST /api 503
10.1.1.3 GET /x 502
10.1.1.3 GET /y 502
10.1.1.2 GET /z 504
""")
        write("/var/log/lfcs/agent.log","""GET|/api/orders|404|Safari Mobile
POST|/api/items|401|Chrome Desktop
GET|/web/home|404|Safari Mobile
GET|/api/users|200|Firefox Mobile
PATCH|/api/x|403|Firefox Mobile
""")
        write("/srv/lfcs/app/users.csv","# name,role,shell\nava,operator,/bin/sh\nben,viewer,/bin/sh\ncy,operator,/bin/bash\n")
        write("/srv/lfcs/app/expected.conf","# desired\nPORT=8110\nMODE=prod\nCACHE=yes\n")
        write("/srv/lfcs/app/actual.conf","PORT=8110\nMODE=dev\nCACHE=no\nEXTRA=true\n")
        write("/var/log/lfcs/service.log","""10:14:59 INFO before
10:15:00 ERROR first failure
10:30:10 WARN ignored
10:45:59 ERROR final failure
10:46:00 ERROR after
""")
        write("/srv/lfcs/app/teams.txt"," # teams\n Alpha \nbeta\nALPHA\n\n Gamma  \n")
    elif sid.startswith("archive-"):
        base=pathlib.Path("/srv/lfcs/archives/work"); (base/"conf.d").mkdir(parents=True,exist_ok=True); (base/"logs").mkdir(exist_ok=True)
        write(base/"conf.d/app.conf","mode=exam\n",0o640); write(base/"conf.d/net.conf","port=8110\n",0o644); write(base/"logs/app.log","log\n"); write(base/"README","bundle\n")
        run("tar -C /srv/lfcs/archives/work -czf /srv/lfcs/archives/one.tar.gz .; tar -C /srv/lfcs/archives/work -cJf /srv/lfcs/archives/two.tar.xz ./conf.d ./README; tar -C /srv/lfcs/archives/work -czf /srv/lfcs/archives/records.tar.gz .; tar -C /srv/lfcs/archives/work -cjf /srv/lfcs/archives/bundle.tar.bz2 conf.d logs README")
    elif sid.startswith("redirection-"):
        write("/usr/local/bin/lfcs-streams","#!/bin/sh\necho out-one\necho err-one >&2\necho out-two\necho err-two >&2\nexit 7\n",0o755)
        if sid=="redirection-02": write("/tmp/stream-combined","existing\n")
    elif sid.startswith("links-"):
        root=pathlib.Path("/srv/lfcs/links"); (root/"releases/v1").mkdir(parents=True,exist_ok=True); (root/"releases/v2").mkdir(parents=True,exist_ok=True)
        write(root/"releases/v1/version","v1\n"); write(root/"releases/v2/version","v2\n"); write(root/"config.live","mode=live\n",0o640)
        os.symlink("releases/v1",root/"current")
    elif sid.startswith("permissions-"):
        for g in ("editors","auditors"): run(f"groupadd -f {g}")
        pathlib.Path("/srv/lfcs/shared").mkdir(parents=True,exist_ok=True); write("/srv/lfcs/shared/tool.sh","#!/bin/sh\nexit 0\n",0o604)
        pathlib.Path("/srv/lfcs/bin").mkdir(parents=True,exist_ok=True); write("/srv/lfcs/bin/report-id","#!/bin/sh\nid\n",0o644)
    elif sid=="attributes-01":
        pathlib.Path("/srv/lfcs/ledger").mkdir(parents=True,exist_ok=True); write("/srv/lfcs/ledger/current.log","start\n"); write("/srv/lfcs/ledger/schema.conf","v=1\n")
    elif sid.startswith("git-"):
        git_env = ("GIT_AUTHOR_DATE=2026-01-01T00:00:00Z "
                   "GIT_COMMITTER_DATE=2026-01-01T00:00:00Z")
        if sid=="git-01":
            root=pathlib.Path("/srv/lfcs/git/service"); root.mkdir(parents=True,exist_ok=True); run(f"git -C {root} init -q -b main; git -C {root} config user.email exam@local; git -C {root} config user.name Exam")
            write(root/"app.conf","FEATURE_GATE=false\nAPI_LEVEL=5\n"); run(f"git -C {root} add .; {git_env} git -C {root} commit -qm base")
            for branch,content in (("feature/amber","FEATURE_GATE=true\nAPI_LEVEL=6\n"),("feature/teal","FEATURE_GATE=true\nAPI_LEVEL=7\n"),("feature/violet","FEATURE_GATE=false\nAPI_LEVEL=7\n")):
                run(f"git -C {root} switch -qc {branch} main"); write(root/"app.conf",content); run(f"{git_env} git -C {root} commit -qam {shlex.quote(branch)}")
            run(f"git -C {root} switch -q main; chown -R student:student {root}")
        else:
            root=pathlib.Path("/srv/lfcs/git/banner"); root.mkdir(parents=True,exist_ok=True); run(f"git -C {root} init -q -b main; git -C {root} config user.email exam@local; git -C {root} config user.name Exam")
            write(root/"banner.txt","Base\nOperations\n"); run(f"git -C {root} add .; {git_env} git -C {root} commit -qm operations; git -C {root} switch -qc feature/teal"); write(root/"banner.txt","Base\nTeal\n"); run(f"{git_env} git -C {root} commit -qam teal; git -C {root} switch -q main; chown -R student:student {root}")

def setup_users(sid):
    for g in ("platform","incident","analytics","authors","deployops","monitoring","batch"):
        run(f"groupadd -f {g}")
    if sid=="usermod-01": run("useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m -s /bin/sh -G analytics maren")
    elif sid=="usermod-02":
        run("useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m -s /bin/sh -G analytics devin"); write("/home/devin/keep.txt","keep\n",owner="devin:devin")
    elif sid=="usermod-03":
        run("useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m -s /bin/bash rhea")
        run("usermod -p \"$(openssl passwd -6 -salt lfcs practice)\" rhea")
    elif sid=="usermod-04":
        run("useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m -s /bin/bash -G authors tempwriter"); write("/home/tempwriter/draft.txt","keep\n",owner="tempwriter:tempwriter")
    elif sid.startswith("sudo-"):
        for u in ("maren","backupbot","release"):
            run(f"id {u} >/dev/null 2>&1 || useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m {u}")
        run("id archive >/dev/null 2>&1 || useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m archive")
        if sid=="sudo-03": write("/etc/sudoers.d/93-lfcs-monitor","Cmnd_Alias MONITOR = /usr/bin/journalctl\n%monitoring ALL=(root) PASSWD: MONITOR\n",0o666)
    elif sid=="env-01": run("useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m -s /bin/bash maren")
    elif sid=="env-02": pass
    elif sid=="env-03":
        run("useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m -s /bin/bash devin"); write("/home/devin/.profile","BUILD_ROOT=/tmp/wrong\nexport LOCAL_NOTE=private\n",owner="devin:devin")
    elif sid=="limits-01":
        run("useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m -s /bin/bash maren"); write("/home/maren/.bashrc","# custom prompt\nulimit -n 8192\n",owner="maren:maren")
    elif sid=="limits-02": write("/etc/security/limits.d/92-lfcs-batch.conf","@batch hard nproc 32\n",0o644)

def grade_operations(sid):
    if sid=="sysinfo-01":
        check("kernel release is exact","test \"$(cat /tmp/kernel-release 2>/dev/null)\" = \"$(uname -r)\"")
        check("sysctl value is exact","test \"$(cat /tmp/overcommit-value 2>/dev/null)\" = \"$(sysctl -n vm.overcommit_memory)\"")
        check("default target is exact","test \"$(cat /tmp/default-target 2>/dev/null)\" = \"$(systemctl get-default)\"")
    elif sid=="sysinfo-02":
        check("report has exactly three lines","test \"$(wc -l </tmp/boot-clock-report 2>/dev/null)\" = 3")
        check("hostname is correct","sed -n 1p /tmp/boot-clock-report | grep -qx \"$(hostnamectl --static)\"")
        check("timezone is correct","sed -n 2p /tmp/boot-clock-report | grep -qx \"$(timedatectl show -p Timezone --value)\"")
        check("boot ID is correct", """
            actual=$(sed -n 3p /tmp/boot-clock-report | tr '[:upper:]' '[:lower:]' | tr -d -- '-[:space:]')
            expected=$(cat /proc/sys/kernel/random/boot_id | tr '[:upper:]' '[:lower:]' | tr -d -- '-[:space:]')
            test ${#actual} = 32 && test \"$actual\" = \"$expected\" &&
              ! printf %s \"$actual\" | grep -q '[^0-9a-f]'
        """)
    elif sid=="systemd-04":
        check("service runs as svc-alder","test \"$(systemctl show alder-worker -p User --value)\" = svc-alder")
        check("service is active","systemctl is-active --quiet alder-worker")
        check("service is enabled","systemctl is-enabled --quiet alder-worker")
        check("executable observed correct user","for i in {1..20}; do grep -qx svc-alder /run/alder-user 2>/dev/null && exit 0; sleep 0.1; done; exit 1")
    elif sid=="systemd-05":
        check("vendor unit remains unchanged","! grep -q APP_MODE /etc/systemd/system/pine-api.service")
        check("drop-in sets production mode","systemctl cat pine-api | grep -Eq '^Environment=.*APP_MODE=production'")
        check("service receives environment","grep -qx production /run/pine-mode")
        check("service is active and enabled","systemctl is-active --quiet pine-api && systemctl is-enabled --quiet pine-api")
    elif sid=="systemd-06":
        check("service is unmasked","test \"$(systemctl is-enabled juniper-agent)\" != masked")
        check("service is active and enabled","systemctl is-active --quiet juniper-agent && systemctl is-enabled --quiet juniper-agent")
        check("restart-on-failure is configured","test \"$(systemctl show juniper-agent -p Restart --value)\" = on-failure")
    elif sid=="systemd-07":
        check("web requires data service","systemctl show spruce-web -p Requires --value | grep -qw spruce-data.service")
        check("web starts after data","systemctl show spruce-web -p After --value | grep -qw spruce-data.service")
        check("both services are active and enabled","systemctl is-active --quiet spruce-data spruce-web && systemctl is-enabled --quiet spruce-data spruce-web")
        check("dependency marker was observed","test -f /run/spruce-web-ready")
    elif sid=="systemd-08":
        check("correct EnvironmentFile is loaded","systemctl cat hemlock-job | grep -q 'EnvironmentFile=/etc/lfcs-lab/hemlock.env'")
        check("green result is produced","grep -qx green /run/hemlock-result")
        check("restart policy is on-failure","test \"$(systemctl show hemlock-job -p Restart --value)\" = on-failure")
        check("service is active and enabled","systemctl is-active --quiet hemlock-job && systemctl is-enabled --quiet hemlock-job")
    elif sid=="cron-02":
        check("student job has exact schedule","crontab -u student -l | grep -Eq '^15 +7 +\\* +\\* +1,3,5 +/usr/local/bin/alder-backup --incremental$'")
        check("user crontab has no username field","! crontab -u student -l | grep -Eq ' +student +'")
        check("old system cron file is removed","test ! -e /etc/cron.d/alder-backup")
    elif sid=="cron-03":
        check("root schedule is exact","grep -Eq '^40 +2 +1 +\\* +\\* +root +/usr/local/bin/maple-prune$' /etc/cron.d/maple-prune")
        check("cron file ownership is root","test \"$(stat -c %U:%G /etc/cron.d/maple-prune)\" = root:root")
        check("cron file mode is 0644","test \"$(stat -c %a /etc/cron.d/maple-prune)\" = 644")
    elif sid=="cron-04":
        check("anacron entry has correct period and delay","grep -Eq '^7 +12 +cedar-index +/usr/local/bin/cedar-index$' /etc/anacrontab")
        check("anacron table has no duplicate cedar job","test \"$(grep -c cedar-index /etc/anacrontab)\" = 1")
    elif sid=="process-02":
        check("report contains the owned process PID","test \"$(sed -n 1p /tmp/walnut-report 2>/dev/null)\" = \"$(cat /run/lfcs-lab/extended-walnut.pid)\"")
        check("report contains executable path","sed -n 2p /tmp/walnut-report | grep -qx /usr/bin/sleep")
        check("report contains open data path","sed -n 3p /tmp/walnut-report | grep -qx /srv/lfcs/process/walnut.data")
        check("only walnut process has nice value 12","test \"$(ps -o ni= -p $(cat /run/lfcs-lab/extended-walnut.pid) | tr -d ' ')\" = 12")
    elif sid=="source-01":
        check("leafutil is installed under /usr","test -x /usr/bin/leafutil")
        check("configured prefix is /usr","/usr/bin/leafutil | grep -q 'prefix=/usr'")
        check("IPv6 feature is disabled","/usr/bin/leafutil | grep -q 'ipv6=disabled'")
        check("configure state records requested options","grep -qx 'prefix=/usr' /usr/local/src/leafutil/config.status && grep -qx 'ipv6=disabled' /usr/local/src/leafutil/config.status")
    elif sid=="docker-01":
        check("report has container IP","test \"$(sed -n 1p /tmp/web-fern-report 2>/dev/null)\" = \"$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' web-fern)\"")
        check("report has mount source","sed -n 2p /tmp/web-fern-report | grep -qx /srv/lfcs/fern")
        check("report has host port","sed -n 3p /tmp/web-fern-report | grep -qx 8131")
        check("report has environment value","sed -n 4p /tmp/web-fern-report | grep -qx practice")
        check("container remains running","test \"$(docker inspect -f '{{.State.Running}}' web-fern)\" = true")
    elif sid=="docker-02":
        check("web-ivy is running nginx alpine","test \"$(docker inspect -f '{{.State.Running}}' web-ivy)\" = true && docker inspect -f '{{.Config.Image}}' web-ivy | grep -qx nginx:alpine")
        check("port 8132 publishes container port 80","docker port web-ivy 80/tcp | grep -q ':8132$'")
        check("correct read-only mount is present","docker inspect web-ivy | grep -q /srv/lfcs/ivy && docker inspect -f '{{range .Mounts}}{{if eq .Destination \"/usr/share/nginx/html\"}}{{.RW}}{{end}}{{end}}' web-ivy | grep -qx false")
        check("environment variable is correct","docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' web-ivy | grep -qx LFCS_STAGE=exam")
        check("memory limit is 96 MiB","test \"$(docker inspect -f '{{.HostConfig.Memory}}' web-ivy)\" = 100663296")
        check("published content works","curl -fsS http://127.0.0.1:8132 | grep -q ivy-ready")
    elif sid.startswith("timesync-"):
        if sid=="timesync-01":
            primary = systemd_config_last_value("systemd/timesyncd.conf", "NTP")
            fallback = systemd_config_last_value("systemd/timesyncd.conf", "FallbackNTP")
            check_bool("primary and fallback servers are configured",
                       primary == "time.cloudflare.com" and fallback == "ntp.ubuntu.com")
            minimum = systemd_config_last_value("systemd/timesyncd.conf", "PollIntervalMinSec")
            maximum = systemd_config_last_value("systemd/timesyncd.conf", "PollIntervalMaxSec")
            check_bool("poll interval policy is correct", minimum == "32" and maximum == "1024")
        else:
            check("invalid source is absent","! grep -Rqs invalid.lfcs.invalid /etc/systemd/timesyncd.conf /etc/systemd/timesyncd.conf.d")
            check("primary server and retry policy are correct","systemd-analyze cat-config systemd/timesyncd.conf | grep -q '^NTP=1.1.1.1' && systemd-analyze cat-config systemd/timesyncd.conf | grep -q '^ConnectionRetrySec=30'")
        check("timesyncd is active and enabled","systemctl is-active --quiet systemd-timesyncd && systemctl is-enabled --quiet systemd-timesyncd")
    elif sid.startswith("virt-"):
        v="/srv/lfcs/virt"
        if sid=="virt-01":
            check("report contains both headings","grep -qx ACTIVE /tmp/virt-list && grep -qx ALL /tmp/virt-list")
            check("test domain appears in report","grep -q test /tmp/virt-list")
        elif sid=="virt-02":
            check("domain name and state are recorded","sed -n 1p /tmp/virt-dominfo | grep -qx test && sed -n 2p /tmp/virt-dominfo | grep -Eqi 'running|idle'")
            check("memory and vCPU values are recorded","sed -n 3p /tmp/virt-dominfo | grep -Eq '^[0-9]+$' && sed -n 4p /tmp/virt-dominfo | grep -Eq '^[0-9]+$'")
        elif sid=="virt-03":
            check("lifecycle script has valid shell syntax",f"bash -n {v}/lifecycle.sh")
            for word,msg in (("start","start"),("shutdown","graceful shutdown"),("destroy","force stop"),("autostart","autostart"),("undefine","undefine")): check(f"script includes {msg}",f"grep -Eq 'virsh .*{word}.*exam-elm|virsh .*{word}' {v}/lifecycle.sh")
        elif sid in {"virt-04","virt-05"}:
            f=f"{v}/exam-{'ash' if sid=='virt-04' else 'oak'}.xml"
            check("domain XML is well formed",f"python3 -c 'import xml.etree.ElementTree as E; E.parse(\"{f}\")'")
            if sid=="virt-04":
                check("name, memory, and vCPU are correct",f"grep -q '<name>exam-ash</name>' {f} && grep -Eq '<memory unit=.MiB.>768</memory>' {f} && grep -q '<vcpu>2</vcpu>' {f}")
                check("virtio disk and default network are present",f"grep -q exam-ash.qcow2 {f} && grep -Eq 'target dev=.vda.*bus=.virtio' {f} && grep -Eq 'source network=.default' {f}")
            else:
                check("resources and autostart metadata are correct",f"grep -q '<vcpu>3</vcpu>' {f} && grep -Eq '<memory unit=.MiB.>1024</memory>' {f} && grep -q '<autostart>enabled</autostart>' {f}")
                check("identity, disk, and network remain",f"grep -q '11111111-2222-3333-4444-555555555555' {f} && grep -q exam-oak.qcow2 {f} && grep -q \"network='default'\" {f}")
        elif sid=="virt-06":
            check("qemu-img JSON report is valid","jq -e '.format == \"qcow2\" and .[\"virtual-size\"] == 67108864' /tmp/exam-maple-info")
            check("image virtual size is unchanged","test \"$(qemu-img info --output=json /srv/lfcs/virt/exam-maple.qcow2 | jq -r '.[\"virtual-size\"]')\" = 67108864")
        elif sid=="virt-07":
            check("image remains qcow2","qemu-img info --output=json /srv/lfcs/virt/exam-willow.qcow2 | jq -e '.format==\"qcow2\"'")
            check("image virtual size is exactly 112 MiB","qemu-img info --output=json /srv/lfcs/virt/exam-willow.qcow2 | jq -e '.[\"virtual-size\"]==117440512'")
            check("image remains sparse","test \"$(du -k /srv/lfcs/virt/exam-willow.qcow2 | cut -f1)\" -lt 10240")
        else:
            f=f"{v}/create-{'birch' if sid=='virt-08' else 'cedar'}.sh"
            check("virt-install script has valid shell syntax",f"bash -n {f}")
            name="exam-birch" if sid=="virt-08" else "exam-cedar"; mem="1024" if sid=="virt-08" else "512"; cpu="2" if sid=="virt-08" else "1"
            check("name, memory, and vCPU are correct",f"grep -Eq 'virt-install.*--name(=| +){name}' {f} && grep -Eq -- '--(memory|ram)(=| +){mem}' {f} && grep -Eq -- '--vcpus(=| +){cpu}' {f}")
            check("import, headless graphics, and default network are present",f"grep -q -- '--import' {f} && grep -Eq -- '--graphics(=| +)none' {f} && grep -Eq -- '--network(=| +)(network=)?default' {f}")
            check("correct qcow2 disk is referenced",f"grep -q 'exam-{'birch' if sid=='virt-08' else 'cedar'}.qcow2' {f}")

def grade_network(sid):
    if sid.startswith("nmcli-"):
        name={"nmcli-01":"lfcs-cedar","nmcli-02":"lfcs-aspen","nmcli-03":"lfcs-maple"}[sid]
        device={"nmcli-01":"nmcedar0","nmcli-02":"nmaspen0","nmcli-03":"nmaple0"}[sid]
        address={"nmcli-01":"198.51.100.20/24","nmcli-02":"192.0.2.20/24","nmcli-03":"203.0.113.30/24"}[sid]
        check("requested persistent profile exists",f"nmcli -t -f NAME connection show | grep -qx {name}")
        check_bool("profile is stored on persistent disk", nm_profile_persistent(name))
        check("requested profile is active",f"test \"$(nmcli -g GENERAL.CONNECTION device show {device})\" = {name}")
        check("live IPv4 address is exact",f"ip -4 -o address show dev {device} | grep -qw {address}")
        check("profile cannot supply a default route",f"test \"$(nmcli -g ipv4.never-default connection show {name})\" = yes && ! ip route show default | grep -q 'dev {device}'")
        if sid == "nmcli-02":
            check("persistent route is exact","nmcli -g ipv4.routes connection show lfcs-aspen | tr ';' '\n' | grep -Eq '^198\\.51\\.100\\.0/24 +192\\.0\\.2\\.1( |$)'")
            check("route is active on nmaspen0","ip route show 198.51.100.0/24 | grep -Eq 'via 192\\.0\\.2\\.1 dev nmaspen0'")
        elif sid == "nmcli-03":
            check("new profile autoconnects","test \"$(nmcli -g connection.autoconnect connection show lfcs-maple)\" = yes")
            check("old profile cannot take over","test \"$(nmcli -g connection.autoconnect connection show lfcs-maple-old)\" = no && ! nmcli -t -f NAME connection show --active | grep -qx lfcs-maple-old")
    elif sid.startswith("iptables-"):
        if sid=="iptables-01":
            check("node2 INPUT blocks TCP 9121","ip netns exec node2 iptables -C INPUT -p tcp --dport 9121 -j DROP || ip netns exec node2 iptables -C INPUT -p tcp --dport 9121 -j REJECT")
            check("node1 cannot reach blocked service","! ip netns exec node1 nc -z -w1 10.10.2.10 9121")
            check("established traffic rule is preserved","ip netns exec node2 iptables-save | grep -q -- '--ctstate RELATED,ESTABLISHED.*-j ACCEPT'")
        elif sid=="iptables-02":
            check("node1 source is permitted","ip netns exec node1 nc -z -w2 10.10.2.10 9122")
            check("node3 source is rejected","! ip netns exec node3 nc -z -w1 10.10.2.10 9122")
            check("established traffic rule is preserved","ip netns exec node2 iptables-save | grep -q -- '--ctstate RELATED,ESTABLISHED.*-j ACCEPT'")
            check_bool("source-specific allow precedes conflicting reject",
                       ordered_port_exception("node2", "INPUT", 9122,
                           {"10.10.1.10/32", "10.10.1.0/24"}, "10.10.3.10"))
        elif sid=="iptables-03":
            check("node1 cannot reach node3 service","! ip netns exec node1 nc -z -w1 10.10.3.10 9123")
            check("OUTPUT rule has exact destination and port","ip netns exec node1 iptables-save | grep -Eq -- '-A OUTPUT .*10.10.3.10/32.*--dport 9123.*-(j|g) (DROP|REJECT)'")
            check("node2 connectivity remains","ip netns exec node1 ping -c1 -W1 10.10.2.10")
        elif sid=="iptables-04":
            check("nat OUTPUT REDIRECT rule exists","ip netns exec node2 iptables-save -t nat | grep -Eq -- '-A OUTPUT .*--dport 8184.*REDIRECT.*8084'")
            check("redirected local request works","for i in {1..20}; do ip netns exec node2 curl -fsS http://127.0.0.1:8184 2>/dev/null | grep -q node2-ready && exit 0; sleep 0.1; done; exit 1")
        elif sid=="iptables-05":
            check("IPv4 forwarding is enabled","test \"$(ip netns exec router1 sysctl -n net.ipv4.ip_forward)\" = 1")
            check("DNAT rule maps the requested endpoint","ip netns exec router1 iptables-save -t nat | grep -Eq '8185.*DNAT.*10.10.2.10:8080'")
            check("node1 reaches translated backend","ip netns exec node1 curl -fsS --max-time 2 http://10.10.1.1:8185 | grep -q backend=node2")
            check("return path permits established traffic","ip netns exec node1 curl -fsS --max-time 2 http://10.10.1.1:8185 | grep -q backend=node2")
            check_bool("FORWARD permissions are limited to the translated service or established traffic", dnat_forward_scope())
            check("FORWARD has no unconditional accept","! ip netns exec router1 iptables-save | grep -Eq '^-A FORWARD -j ACCEPT$'")
        elif sid=="iptables-06":
            check("IPv4 forwarding is enabled","test \"$(ip netns exec router1 sysctl -n net.ipv4.ip_forward)\" = 1")
            check("MASQUERADE is scoped to node1 subnet and eth0","ip netns exec router1 iptables-save -t nat | grep -Eq -- '-A POSTROUTING .*10.10.1.0/24.*-o eth0.*-j MASQUERADE'")
            check("other lab subnets are not masqueraded","! ip netns exec router1 iptables-save -t nat | grep -Eq '10.10.[23].0/24.*MASQUERADE'")
            probes = functional_masquerade_probe()
            check_bool("node1 traffic is translated on eth0 and returns", probes["positive"])
            check_bool("node2 out-of-scope traffic is not translated", probes["negative"])
        elif sid=="iptables-07":
            check("FORWARD policy is DROP","ip netns exec router1 iptables -S FORWARD | grep -qx -- '-P FORWARD DROP'")
            check("node1 reaches allowed node3 port","ip netns exec node1 nc -z -w2 10.10.3.10 9127")
            check("other new node1-to-node3 traffic stays blocked","! ip netns exec node1 nc -z -w1 10.10.3.10 8080")
            check("established return traffic is allowed","ip netns exec router1 iptables-save | grep -q -- '--ctstate RELATED,ESTABLISHED.*-j ACCEPT'")
        elif sid=="iptables-08":
            check("node1 reaches the exception","ip netns exec node1 nc -z -w2 10.10.2.10 9128")
            check("node3 remains rejected","! ip netns exec node3 nc -z -w1 10.10.2.10 9128")
            check_bool("allow rule precedes broad reject",
                       ordered_port_exception("node2", "INPUT", 9128,
                           {"10.10.1.10/32", "10.10.1.0/24"}, "10.10.3.10", True))
        elif sid=="iptables-09":
            check("LFCS_PERSIST chain and INPUT jump exist","iptables -S INPUT | grep -q -- '-j LFCS_PERSIST' && iptables -S LFCS_PERSIST")
            check_bool("source allow precedes reject",
                       ordered_port_exception(None, "LFCS_PERSIST", 8139,
                           {"10.10.1.0/24"}, "10.10.3.10", True))
            check("saved rules restore-test successfully","iptables-restore --test </etc/iptables/rules.v4")
            check("saved file contains custom chain","grep -q LFCS_PERSIST /etc/iptables/rules.v4")
            check("Docker firewall chains remain intact","iptables -S DOCKER-USER >/dev/null && iptables -t nat -S DOCKER >/dev/null")
            check_bool("saved rules preserve required Docker chains",
                       saved_iptables_preserves_docker())
        else:
            check("FORWARD policy is DROP","ip netns exec router1 iptables -S FORWARD | grep -qx -- '-P FORWARD DROP'")
            check("node1 reaches node3 service","ip netns exec node1 nc -z -w2 10.10.3.10 9130")
            check("node2 cannot reach node3 service","! ip netns exec node2 nc -z -w1 10.10.3.10 9130")
            check("return traffic is allowed","ip netns exec router1 iptables-save | grep -q -- '--ctstate RELATED,ESTABLISHED.*-j ACCEPT'")
            check("router rules were saved and validate","test -s /etc/iptables/lfcs-router.v4 && iptables-restore --test </etc/iptables/lfcs-router.v4")
    elif sid.startswith("nginx-"):
        check("nginx configuration validates","nginx -t")
        check("nginx is active and enabled","systemctl is-active --quiet nginx && systemctl is-enabled --quiet nginx")
        if sid=="nginx-01":
            check_bool("effective configuration contains the requested server",
                       nginx_server_has(8111,
                           r"\breturn\s+200\s+[\"']?amber-ready"))
            check("listener is bound on all IPv4 addresses","ss -lnt | grep -Eq '0.0.0.0:8111|\\*:8111'")
            check("listener returns exact response","curl -fsS http://127.0.0.1:8111 | cmp - <(printf 'amber-ready\\n')")
        elif sid=="nginx-02":
            check("alder site is enabled","test -L /etc/nginx/sites-enabled/lfcs-ext-alder")
            check("alder content is served","curl -fsS http://127.0.0.1:8112 | grep -qx alder-ready")
        elif sid=="nginx-03":
            check("reverse proxy reaches node2","curl -fsS http://127.0.0.1:8113 | grep -q backend=node2")
            check_bool("port 8113 preserves the Host header",
                       nginx_server_has(8113,
                           r"\bproxy_set_header\s+Host\s+\$(?:host|http_host)\s*;"))
        elif sid=="nginx-04":
            check("API path reaches backend with prefix stripped","curl -fsS http://127.0.0.1:8114/api/ | grep -q backend=node2")
            check("outside path returns 404","test \"$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8114/)\" = 404")
        elif sid=="nginx-05":
            check("both listeners bind all IPv4 addresses","ss -lnt | grep -Eq '0.0.0.0:8115|\\*:8115' && ss -lnt | grep -Eq '0.0.0.0:8116|\\*:8116'")
            check("port 8115 responds","curl -fsS http://127.0.0.1:8115 | grep -qx twin-ready")
            check("port 8116 responds","curl -fsS http://127.0.0.1:8116 | grep -qx twin-ready")
        else:
            check_bool("port 8446 uses the supplied certificate and key",
                       nginx_server_has(8446,
                           r"\bssl_certificate\s+/etc/lfcs/tls/fern/server\.crt\s*;") and
                       nginx_server_has(8446,
                           r"\bssl_certificate_key\s+/etc/lfcs/tls/fern/server\.key\s*;"))
            check("TLS key has mode 0600","test \"$(stat -c %a /etc/lfcs/tls/fern/server.key)\" = 600")
            check("HTTPS endpoint works","curl -kfsS https://127.0.0.1:8446 | grep -qx fern-secure")
    elif sid.startswith("ssh-match-"):
        check("sshd configuration validates","sshd -t -f /etc/lfcs-lab/sshd-match.conf")
        if sid=="ssh-match-01":
            check("buildbot password login is disabled","sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=buildbot,host=localhost,addr=127.0.0.1 | grep -qx 'passwordauthentication no'")
            check("buildbot public keys are enabled","sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=buildbot,host=localhost,addr=127.0.0.1 | grep -qx 'pubkeyauthentication yes'")
            check("global password setting remains yes","sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=student,host=localhost,addr=127.0.0.1 | grep -qx 'passwordauthentication yes'")
        elif sid=="ssh-match-02":
            check("group receives internal-sftp","sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=buildbot,host=localhost,addr=127.0.0.1,laddr=127.0.0.1,lport=2229 | grep -qx 'forcecommand internal-sftp'")
            check("group has X11 disabled","sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=buildbot,host=localhost,addr=127.0.0.1 | grep -qx 'x11forwarding no'")
            check("student remains unrestricted","sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=student,host=localhost,addr=127.0.0.1 | grep -qx 'forcecommand none'")
        else:
            check("root login is globally disabled","sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=root,host=localhost,addr=127.0.0.1 | grep -qx 'permitrootlogin no'")
            check("deployer receives requested banner","sshd -T -f /etc/lfcs-lab/sshd-match.conf -C user=deployer,host=localhost,addr=127.0.0.1 | grep -qx 'banner /etc/issue.net'")
            check("effective banner report is exact","grep -qx /etc/issue.net /tmp/deployer-banner")

def grade_storage(sid):
    if sid=="lvm-01":
        check("disk2 has no allocated extents","test \"$(pvs --noheadings -o pv_used /dev/lfcs-disk2 2>/dev/null | tr -dc 0-9)\" = 0")
        check("disk2 was removed from orchard","! pvs --noheadings -o vg_name /dev/lfcs-disk2 2>/dev/null | grep -qw orchard")
        check("filesystem remains mounted","findmnt -rn -S /dev/mapper/orchard-harvest -o TARGET | grep -qx /mnt/lfcs/orchard")
        check("sentinel data survives","grep -qx preserve-orchard /mnt/lfcs/orchard/sentinel")
    elif sid=="lvm-02":
        check("disk2 is removed from oldfruit","! pvs --noheadings -o vg_name /dev/lfcs-disk2 | grep -qw oldfruit")
        check("disk2 belongs to freshfruit","pvs --noheadings -o vg_name /dev/lfcs-disk2 | grep -qw freshfruit")
        check("crates LV is at least 96 MiB","lvs --noheadings --units m --nosuffix -o lv_size freshfruit/crates | awk '{exit !($1>=96)}'")
        check("crates is ext4 and mounted","test \"$(blkid -s TYPE -o value /dev/freshfruit/crates)\" = ext4 && findmnt -rn -S /dev/mapper/freshfruit-crates -o TARGET | grep -qx /mnt/lfcs/crates")
    elif sid=="lvm-03":
        check("data LV grew by at least 80 MiB","lvs --noheadings --units m --nosuffix -o lv_size garden/data | awk '{exit !($1>=208)}'")
        check("ext4 filesystem grew with LV","df -BM --output=size /mnt/lfcs/garden | tail -1 | tr -dc 0-9 | awk '{exit !($1>=165)}'")
        check("sentinel data survives","grep -qx garden-safe /mnt/lfcs/garden/sentinel")
    elif sid=="lvm-04":
        check("disk2 extends observatory","pvs --noheadings -o vg_name /dev/lfcs-disk2 | grep -qw observatory")
        check("logs LV grew by at least 96 MiB","lvs --noheadings --units m --nosuffix -o lv_size observatory/logs | awk '{exit !($1>=410)}'")
        check("XFS filesystem uses grown space","df -BM --output=size /mnt/lfcs/observatory | tail -1 | tr -dc 0-9 | awk '{exit !($1>=340)}'")
        check("sentinel data survives","grep -qx stars-safe /mnt/lfcs/observatory/sentinel")
    elif sid=="mount-01":
        check("mount has noexec and nosuid","findmnt -no OPTIONS /mnt/lfcs/noexec | grep -qw noexec && findmnt -no OPTIONS /mnt/lfcs/noexec | grep -qw nosuid")
        check("direct execution is blocked","! /mnt/lfcs/noexec/check.sh")
        check_bool("fstab uses UUID and required options", fstab_entry(
            "/mnt/lfcs/noexec", "ext4", uuid_device="/dev/lfcs-disk1",
            required_options=("noexec", "nosuid")))
    elif sid=="mount-02":
        check("archive mount is read-only","findmnt -no OPTIONS /mnt/lfcs/archive | grep -qw ro")
        check("sentinel data survives","grep -qx archive-safe /mnt/lfcs/archive/sentinel")
        check_bool("fstab uses real UUID and ro", fstab_entry(
            "/mnt/lfcs/archive", "ext4", uuid_device="/dev/lfcs-disk1",
            required_options=("ro",)))
        check("fstab validates","mount -a")
    elif sid=="mount-03":
        check_bool("fstab uses real UUID and ext4", fstab_entry(
            "/mnt/lfcs/recovery", "ext4", uuid_device="/dev/lfcs-disk1"))
        check_bool("persistent noexec option is present", fstab_entry(
            "/mnt/lfcs/recovery", "ext4", uuid_device="/dev/lfcs-disk1",
            required_options=("noexec",)))
        check("fstab validates","mount -a")
        check("filesystem is mounted","findmnt -T /mnt/lfcs/recovery -t ext4")
    elif sid=="nfs-01":
        context = nfs_client_mount_context()
        check_bool("export is restricted read-write to node1 subnet",
                   nfs_export_restricted("/srv/lfcs/projects", "10.10.1.0/24"))
        check("export is active","exportfs -v | grep -q /srv/lfcs/projects")
        check_bool("exact NFS source is mounted read-write", mount_entry(
            "/mnt/lfcs/projects", {"nfs", "nfs4"},
            source="10.10.0.2:/srv/lfcs/projects", required_options=("rw",), context=context))
        check("mounted content comes from the requested backend",
              context + "cmp /srv/lfcs/projects/README /mnt/lfcs/projects/README")
        check("client can write through the requested export",
              context + "bash -lc " + shlex.quote("p=/mnt/lfcs/projects/.lfcs-grade-$$; trap 'sudo -u student rm -f \"$p\"' EXIT; sudo -u student sh -c 'printf nfs-rw >\"$1\" && grep -qx nfs-rw \"$1\"' sh \"$p\""))
        check_bool("persistent NFS entry has exact source and _netdev", any(fstab_entry(
            "/mnt/lfcs/projects", fstype, source="10.10.0.2:/srv/lfcs/projects",
            required_options=("_netdev",), normalize_target=True) for fstype in ("nfs", "nfs4")))
    elif sid=="sshfs-01":
        source = out("findmnt -rn --target /mnt/lfcs/remote -o SOURCE")
        source_ok = sshfs_student_connection(source)
        check_bool("SSHFS source is student on node2 at the exact remote path",
                   source_ok and mount_entry("/mnt/lfcs/remote", "fuse.sshfs",
                                             source=source, required_options=("ro",)))
        check("remote content matches the node2 backend",
              "sudo -u student cmp /srv/lfcs/node2/index.html /mnt/lfcs/remote/index.html")
        uid = out("id -u student"); gid = out("id -g student")
        check_bool("mount uses the student UID and primary GID", mount_entry(
            "/mnt/lfcs/remote", "fuse.sshfs", source=source,
            required_options=(f"user_id={uid}", f"group_id={gid}")))
        check("supplied private key remains student-owned mode 0600",
              "test \"$(stat -c %U:%a /srv/lfcs/keys/exam)\" = student:600")
        check("node2 authorizes the supplied exam key exclusively",
              "test \"$(grep -vc '^[[:space:]]*#' /home/student/.ssh/authorized_keys)\" = 1 && cmp /srv/lfcs/keys/exam.pub /home/student/.ssh/authorized_keys")
    elif sid=="nbd-01":
        check("supplied amber export is active and attached","systemctl is-active --quiet nbd-server && grep -Eq '^\\[amber\\]$' /etc/nbd-server/conf.d/amber.conf && grep -Eq '^[[:space:]]*exportname[[:space:]]*=[[:space:]]*/var/lib/lfcs-disks/amber.img[[:space:]]*$' /etc/nbd-server/conf.d/amber.conf && test \"$(blockdev --getsize64 /dev/nbd0)\" = \"$(stat -c %s /var/lib/lfcs-disks/amber.img)\" && fuser /var/lib/lfcs-disks/amber.img >/dev/null 2>&1")
        check("NBD filesystem is ext4","test \"$(blkid -s TYPE -o value /dev/nbd0)\" = ext4")
        check("NBD is mounted at requested path","findmnt -rn -S /dev/nbd0 -o TARGET | grep -qx /mnt/lfcs/amber")
        check("sentinel content is correct","grep -qx amber-ready /mnt/lfcs/amber/sentinel")
    elif sid=="autofs-01":
        check_bool("exact indirect master and projects map use NFS without local bind substitution",
                   autofs_indirect_map("/mnt/lfcs/on-demand", "projects",
                                       "localhost:/srv/lfcs/projects"))
        check("autofs is active and enabled","systemctl is-active --quiet autofs && systemctl is-enabled --quiet autofs")
        check("access returns requested backend content",
              "grep -qx projects-ready /mnt/lfcs/on-demand/projects/README")
        check_bool("trigger produces the exact NFS backing source", mount_entry(
            "/mnt/lfcs/on-demand/projects", {"nfs", "nfs4"},
            source="localhost:/srv/lfcs/projects", required_options=("rw",)))
        check("autofs mount is not in fstab","! grep -q /mnt/lfcs/on-demand /etc/fstab")
    elif sid=="swap-01":
        check("swap file has requested apparent size","test \"$(stat -c %s /var/lib/lfcs-lab/exam.swap)\" = 67108864")
        check("swap file mode is 0600","test \"$(stat -c %a /var/lib/lfcs-lab/exam.swap)\" = 600")
        check("swap file is active","swapon --show=NAME --noheadings | grep -qx /var/lib/lfcs-lab/exam.swap")
        check_bool("swap file has exact persistent entry", fstab_entry(
            "none", "swap", source="/var/lib/lfcs-lab/exam.swap", required_options=("sw",)))

def grade_commands(sid):
    if sid=="find-01":
        check("only the two owner/size matches were copied","test \"$(find /tmp/hazel-large -maxdepth 1 -type f -printf '%f\\n' 2>/dev/null | sort | paste -sd, -)\" = large-a")
        check("copied content and ownership source are correct","cmp /srv/lfcs/find/owner/large-a /tmp/hazel-large/large-a")
    elif sid=="find-02": check("recent config report is exact","printf '/srv/lfcs/find/recent.conf\\n' | diff -u - /tmp/recent-configs")
    elif sid=="find-03":
        check("exact-mode files moved","test -f /srv/lfcs/quarantine/exact-a && test -f /srv/lfcs/quarantine/exact-b")
        check("other-mode file remains","test -f /srv/lfcs/find/perm/other")
        check("no exact-mode source remains","! find /srv/lfcs/find/perm -type f -perm 0640 | grep -q .")
    elif sid=="find-04":
        check("old matching cache file was deleted","test ! -e /srv/lfcs/find/cache/old.tmp")
        check("new and foreign cache files remain","test -f /srv/lfcs/find/cache/new.tmp && test -f /srv/lfcs/find/cache/foreign.tmp")
    elif sid=="find-05": check("media report contains only live images","printf '/srv/lfcs/find/media/live/A.JPG\\n/srv/lfcs/find/media/live/b.png\\n' | diff -u - /tmp/image-list")
    elif sid=="find-06":
        check("report identifies only executable SUID helper",r"grep -q '/srv/lfcs/find/bin/helper$' /tmp/suid-audit && ! grep -q '/plain$\|/data$' /tmp/suid-audit")
        check("report contains device, inode, mode, owner, and path","awk 'NF>=5 && $NF==\"/srv/lfcs/find/bin/helper\" {ok=1} END{exit !ok}' /tmp/suid-audit")
    elif sid=="find-07":
        check("only files inside time window were copied","test \"$(find /tmp/window -maxdepth 1 -type f -printf '%f\\n' | sort | paste -sd, -)\" = inside-a,inside-b")
        check("timestamps were preserved","test \"$(stat -c %Y /tmp/window/inside-a)\" = \"$(stat -c %Y /srv/lfcs/find/inbox/inside-a)\"")
    elif sid=="find-08":
        check("empty regular files were removed","test ! -e /srv/lfcs/find/staging/empty-a && test ! -e /srv/lfcs/find/staging/empty-b")
        check("data file and empty directory remain","test -f /srv/lfcs/find/staging/data && test -d /srv/lfcs/find/staging/empty-dir")
        check("remaining count report is exact","grep -qx 1 /tmp/staging-count")
    elif sid=="text-01": check("5xx count report is exact","printf '2 10.1.1.1\\n2 10.1.1.3\\n1 10.1.1.2\\n' | diff -u - /tmp/5xx-by-ip")
    elif sid=="text-02": check("compound regex output is exact","printf 'GET|/api/orders|404|Safari Mobile\\nPATCH|/api/x|403|Firefox Mobile\\n' | diff -u - /tmp/mobile-errors")
    elif sid=="text-03": check("only operator /bin/sh record changed","printf '# name,role,shell\\nava,operator,/bin/bash\\nben,viewer,/bin/sh\\ncy,operator,/bin/bash\\n' | diff -u - /srv/lfcs/app/users.csv")
    elif sid=="text-04": check("drift key list is exact","printf 'CACHE\\nEXTRA\\nMODE\\n' | diff -u - /tmp/config-drift")
    elif sid=="text-05": check("error window output is exact","printf 'first failure\\nfinal failure\\n' | diff -u - /tmp/error-window")
    elif sid=="text-06": check("normalised team list is exact","printf 'alpha\\nbeta\\ngamma\\n' | diff -u - /tmp/team-names")
    elif sid=="archive-01": check("common member report is exact","printf './README\\n./conf.d/app.conf\\n./conf.d/net.conf\\n' | diff -u - /tmp/common-members")
    elif sid=="archive-02":
        check("new xz archive is valid","tar -tJf /tmp/records.tar.xz >/dev/null")
        check("source gzip archive is preserved","test -s /srv/lfcs/archives/records.tar.gz")
        check("archives have equivalent members and contents","d=$(mktemp -d); mkdir $d/a $d/b; tar -xzf /srv/lfcs/archives/records.tar.gz -C $d/a; tar -xJf /tmp/records.tar.xz -C $d/b; diff -qr $d/a $d/b")
    elif sid=="archive-03":
        check("selected conf subtree is extracted","test -f /tmp/bundle-selected/conf.d/app.conf && test -f /tmp/bundle-selected/conf.d/net.conf")
        check("unrequested content is absent","test ! -e /tmp/bundle-selected/logs && test ! -e /tmp/bundle-selected/README")
        check("stored mode is preserved","test \"$(stat -c %a /tmp/bundle-selected/conf.d/app.conf)\" = 640")
    elif sid=="redirection-01":
        check("stdout is exact","printf 'out-one\\nout-two\\n' | diff -u - /tmp/stream.out")
        check("stderr is exact","printf 'err-one\\nerr-two\\n' | diff -u - /tmp/stream.err")
        check("exit status is exact","grep -qx 7 /tmp/stream.status")
    elif sid=="redirection-02": check("combined append log contains two complete runs","test \"$(head -1 /tmp/stream-combined)\" = existing && test \"$(grep -c '^out-one$' /tmp/stream-combined)\" = 2 && test \"$(grep -c '^err-two$' /tmp/stream-combined)\" = 2")
    elif sid=="redirection-03":
        check("stdout count is exact","grep -qx 2 /tmp/stdout-count")
        check("stderr is not piped","printf 'err-one\\nerr-two\\n' | diff -u - /tmp/pipeline.err")
        check("producer status is retained","grep -qx 7 /tmp/producer.status")
    elif sid=="links-01":
        check("current is a relative symlink","test -L /srv/lfcs/links/current && test \"$(readlink /srv/lfcs/links/current)\" = releases/v2")
        check("link resolves to version 2","grep -qx v2 /srv/lfcs/links/current/version")
    elif sid=="links-02":
        check("backup and live names share an inode","test \"$(stat -c %d:%i /srv/lfcs/links/config.live)\" = \"$(stat -c %d:%i /srv/lfcs/links/config.backup)\"")
        check("hard-link count is two","test \"$(stat -c %h /srv/lfcs/links/config.live)\" = 2")
        check("content and mode are preserved","grep -qx mode=live /srv/lfcs/links/config.backup && test \"$(stat -c %a /srv/lfcs/links/config.backup)\" = 640")
    elif sid=="permissions-01":
        check("shared directory has exact group and mode","test \"$(stat -c %G:%a /srv/lfcs/shared)\" = editors:2770")
        check("tool has group ownership and executable mode","test \"$(stat -c %G:%a /srv/lfcs/shared/tool.sh)\" = editors:750")
    elif sid=="permissions-02": check("helper has exact owner, group, and SUID mode","test \"$(stat -c %U:%G:%a /srv/lfcs/bin/report-id)\" = root:auditors:4750")
    elif sid=="attributes-01":
        check("ledger is append-only","lsattr /srv/lfcs/ledger/current.log | grep -Eq -- '^-*a-'")
        check("schema is immutable","lsattr /srv/lfcs/ledger/schema.conf | grep -Eq -- '^-*i-'")
        check("attribute report contains both paths","grep -q /srv/lfcs/ledger/current.log /tmp/ledger-attributes && grep -q /srv/lfcs/ledger/schema.conf /tmp/ledger-attributes")
    elif sid=="git-01":
        check("selected branch is exact","grep -qx feature/teal /tmp/selected-branch")
        check("repository remains on main and clean","test \"$(git -c safe.directory=/srv/lfcs/git/service -C /srv/lfcs/git/service branch --show-current)\" = main && test -z \"$(git -c safe.directory=/srv/lfcs/git/service -C /srv/lfcs/git/service status --porcelain)\"")
    elif sid=="git-02":
        check("feature commit is merged","git -c safe.directory=/srv/lfcs/git/banner -C /srv/lfcs/git/banner merge-base --is-ancestor feature/teal main")
        check("banner contains required lines exactly once","test \"$(grep -cx Base /srv/lfcs/git/banner/banner.txt)\" = 1 && test \"$(grep -cx Operations /srv/lfcs/git/banner/banner.txt)\" = 1 && test \"$(grep -cx Teal /srv/lfcs/git/banner/banner.txt)\" = 1")
        check("merge resolution commit message is exact","git -c safe.directory=/srv/lfcs/git/banner -C /srv/lfcs/git/banner log -1 --format=%s | grep -qx 'integrate teal'")
        check("working tree is clean","test -z \"$(git -c safe.directory=/srv/lfcs/git/banner -C /srv/lfcs/git/banner status --porcelain)\"")

def grade_users(sid):
    if sid=="usermod-01":
        check("primary group is platform","test \"$(id -gn maren)\" = platform")
        check("both supplementary groups remain","id -nG maren | grep -qw analytics && id -nG maren | grep -qw incident")
        check("shell is Bash","getent passwd maren | grep -q ':/bin/bash$'")
        check("home path remains unchanged","getent passwd maren | grep -q ':/home/maren:'")
    elif sid=="usermod-02":
        check("home path moved","getent passwd devin | grep -q ':/srv/home/devin:' && test -d /srv/home/devin")
        check("home data and ownership survive","test \"$(stat -c %U:%G /srv/home/devin/keep.txt)\" = devin:devin")
        check("shell is Bash","getent passwd devin | grep -q ':/bin/bash$'")
        check("analytics membership remains","id -nG devin | grep -qw analytics")
    elif sid=="usermod-03":
        check("account expiry is exactly 2026-09-20","getent shadow rhea | awk -F: '$8==20716 {ok=1} END {exit !ok}'")
        check("maximum and minimum age are correct","getent shadow rhea | awk -F: '$4==2 && $5==21 {ok=1} END {exit !ok}'")
        check("warning period is correct","getent shadow rhea | awk -F: '$6==5 {ok=1} END {exit !ok}'")
        check("account is not locked","passwd -S rhea | awk '$2==\"P\" {ok=1} END {exit !ok}' && getent shadow rhea | awk -F: '$2 !~ /^[!*]/ {ok=1} END {exit !ok}'")
        check("shell, home, and primary group are unchanged","getent passwd rhea | awk -F: '$6==\"/home/rhea\" && $7==\"/bin/bash\" {ok=1} END {exit !ok}' && test \"$(id -gn rhea)\" = rhea && test \"$(id -nG rhea)\" = rhea")
    elif sid=="usermod-04":
        check("renamed user and group exist","getent passwd rowan && test \"$(id -gn rowan)\" = rowan")
        check("old identity is absent","! getent passwd tempwriter && ! getent group tempwriter")
        check("home moved with owned data","getent passwd rowan | grep -q ':/home/rowan:' && test \"$(stat -c %U:%G /home/rowan/draft.txt)\" = rowan:rowan")
        check("authors membership remains","id -nG rowan | grep -qw authors")
    elif sid.startswith("sudo-"):
        file={"sudo-01":"/etc/sudoers.d/91-lfcs-maren","sudo-02":"/etc/sudoers.d/92-lfcs-deployops","sudo-03":"/etc/sudoers.d/93-lfcs-monitor","sudo-04":"/etc/sudoers.d/94-lfcs-backupbot"}[sid]
        check("sudoers fragment validates",f"test \"$(stat -c %a {file})\" = 440 && visudo -cf {file}")
        if sid=="sudo-01":
            check("exact nginx restart is passwordless",r"sudo -l -U maren | grep -Eq '\(root\) NOPASSWD: /usr/bin/systemctl restart nginx'")
            check("no broad ALL command is granted",fr"! grep -Eq 'NOPASSWD: *ALL|\) *ALL$' {file}")
        elif sid=="sudo-02":
            check("group may run exact install pattern as release",fr"sudo -l -U $(getent group deployops | cut -d: -f4 | cut -d, -f1) 2>/dev/null | grep -Eq '\(release\).* /usr/bin/install -m 0644 .* /srv/releases/' || grep -Eq '^%deployops .*\(release\).* /usr/bin/install -m 0644 .* /srv/releases/' {file}")
            check("rule still requires a password",f"! grep -q NOPASSWD {file}")
        elif sid=="sudo-03":
            check("monitor alias contains only requested commands",f"grep -Eq '^Cmnd_Alias +MONITOR *= */usr/bin/journalctl, */usr/bin/systemctl status \\*$' {file}")
            check("monitoring group gets passwordless alias",f"grep -Eq '^%monitoring .*NOPASSWD: *MONITOR$' {file}")
        else:
            check("backupbot has exact run-as rsync rule",fr"grep -Eq '^backupbot .*\(archive\) *NOPASSWD: */usr/bin/rsync \*$' {file}")
            check("no setenv or ALL grant exists",fr"! grep -Eq 'SETENV|NOPASSWD: *ALL|\) *ALL$' {file}")
    elif sid=="env-01":
        check("region is system-wide and exported","grep -RqsE '(^|export +)LFCS_REGION=eu-west' /etc/environment /etc/profile /etc/profile.d")
        check("maren project is exported","grep -Eq '^export +PROJECT=cedar$' /home/maren/.profile")
        check("project is not system-wide","! grep -Rqs PROJECT=cedar /etc/environment /etc/profile /etc/profile.d")
    elif sid=="env-02":
        check("skel profile has exported editor","grep -Eq '^export +EDITOR=vim$' /etc/skel/.profile")
        check("skel profile has umask 027","grep -Eq '^umask +027$' /etc/skel/.profile")
        check("new user received both defaults","grep -Eq '^export +EDITOR=vim$' /home/sampleleaf/.profile && grep -Eq '^umask +027$' /home/sampleleaf/.profile")
    elif sid=="env-03":
        check("BUILD_ROOT is exported correctly","grep -Eq '^export +BUILD_ROOT=/srv/build$' /home/devin/.profile")
        check("LOCAL_NOTE remains unexported","grep -Eq '^LOCAL_NOTE=' /home/devin/.profile && ! grep -Eq '^export +LOCAL_NOTE' /home/devin/.profile")
        check("variables are not system-wide","! grep -RqsE 'BUILD_ROOT|LOCAL_NOTE' /etc/environment /etc/profile /etc/profile.d")
    elif sid=="limits-01":
        check("temporary bashrc workaround is removed","! grep -q 'ulimit +-n' /home/maren/.bashrc")
        check("soft nofile limit is persistent","awk '$1==\"maren\" && $2==\"soft\" && $3==\"nofile\" && $4==\"4096\" {n++} END{exit !(n==1)}' /etc/security/limits.d/91-lfcs.conf")
        check("hard nofile limit is persistent","awk '$1==\"maren\" && $2==\"hard\" && $3==\"nofile\" && $4==\"8192\" {n++} END{exit !(n==1)}' /etc/security/limits.d/91-lfcs.conf")
    elif sid=="limits-02":
        check("group soft and hard nproc are correct","awk '$1==\"@batch\" && $2==\"soft\" && $3==\"nproc\" && $4==\"64\" {s++} $1==\"@batch\" && $2==\"hard\" && $3==\"nproc\" && $4==\"96\" {h++} END{exit !(s==1 && h==1)}' /etc/security/limits.d/92-lfcs-batch.conf")
        check("group maxlogins is correct","awk '$1==\"@batch\" && $2==\"-\" && $3==\"maxlogins\" && $4==\"3\" {n++} END{exit !(n==1)}' /etc/security/limits.d/92-lfcs-batch.conf")
        check("contradictory hard nproc entry is absent","awk '$1==\"@batch\" && $2==\"hard\" && $3==\"nproc\" {n++} END{exit !(n==1)}' /etc/security/limits.d/92-lfcs-batch.conf")

def grade_one(sid):
    if sid.startswith(("sysinfo-","systemd-","cron-","process-","source-","docker-","timesync-","virt-")): grade_operations(sid)
    elif sid.startswith(("nmcli-","iptables-","nginx-","ssh-match-")): grade_network(sid)
    elif sid.startswith(("lvm-","mount-","nfs-","sshfs-","nbd-","autofs-","swap-")): grade_storage(sid)
    elif sid.startswith(("find-","text-","archive-","redirection-","links-","permissions-","attributes-","git-")): grade_commands(sid)
    elif sid.startswith(("usermod-","sudo-","env-","limits-")): grade_users(sid)
    else: print(f"FAIL|grader is not implemented for {sid}")

def reset_all():
    run("/usr/local/lib/lfcs/ssh-ownership.py reset-all")
    clean_common()
    for sid in ("find-01","usermod-01","timesync-01","virt-01","nmcli-01","ssh-match-01","autofs-01"):
        reset_one(sid)
    for sid in ("commands-01","commands-02","operations-01","operations-02","operations-03","operations-04","operations-05","operations-06","operations-07","operations-08","networking-01","advanced-09","advanced-10","advanced-11","advanced-12","opsusers-01","opsusers-02","opsusers-03","opsusers-04","opsusers-05","opsusers-06","opsusers-07","opsusers-08","opsusers-09","opsusers-10","opsusers-11","opsusers-12","storage-10","storage-11","storage-12"):
        run(f"/usr/local/lib/lfcs/scenario-engine.sh reset {sid}")
    run("rm -f /etc/systemd/timesyncd.conf.d/95-lfcs-networking.conf; "
        "install -d -o root -g root -m 0755 /run/sshd; "
        "systemctl restart systemd-timesyncd")
    restore_student_admin()
    run("/usr/local/lib/lfcs/ensure-host-access.sh")

if __name__ == "__main__":
    STATE.mkdir(parents=True,exist_ok=True); RUN.mkdir(parents=True,exist_ok=True); OWNED.mkdir(parents=True,exist_ok=True)
    if MODE == "setup": setup_one(ID)
    elif MODE == "reset": reset_one(ID)
    elif MODE == "grade": grade_one(ID)
    elif MODE == "reset-all": reset_all()
    else: raise SystemExit("usage: extended-engine.py setup|reset|grade ID")
