#!/usr/bin/env python3
import hashlib, hmac, json, os, pathlib, re, secrets, shutil, subprocess, sys, time
from datetime import datetime, timezone
from catalog import LABS, BY_ID, MOCKS, MINIS
from solutions import solution_for
from host_platform import (host_kind, host_memory, kvm_access, redirected,
                           version_from, version_label, windows_allocated_kb, windows_hypervisor,
                           windows_local_ntfs)

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
LIMA_HOME = ROOT / ".lima"
if redirected(STATE) or redirected(LIMA_HOME):
    raise SystemExit("Refusing symlinked candidate state or Lima home")
os.environ["LIMA_HOME"] = str(LIMA_HOME)
PROGRESS = pathlib.Path(os.environ.get("LFCS_PROGRESS_PATH", STATE / "progress.json"))
if not PROGRESS.resolve().is_relative_to(ROOT) or redirected(PROGRESS):
    raise SystemExit("Refusing progress path outside the candidate or through a symlink")
BASELINE = STATE / "storage-baseline.json"
INSTANCE = "lfcs-rc-ubuntu"
SPECIAL_INSTANCE = "lfcs-rc-fedora"
OWNERSHIP = STATE / "vm-ownership.json"
SPECIAL_HOST = "lfcs-special"
NAMESPACES = {"node1", "node2", "node3", "router1"}
STUDENT_SUDOERS = "/etc/sudoers.d/00-lfcs-student-admin"
RUNTIME_SCRIPTS = (
    ("provisioning/host-access.sh", "/usr/local/lib/lfcs/ensure-host-access.sh"),
    ("lib/topology.sh", "/usr/local/lib/lfcs/topology.sh"),
    ("lib/storage.sh", "/usr/local/lib/lfcs/storage.sh"),
    ("lib/nginx-ownership.py", "/usr/local/lib/lfcs/nginx-ownership.py"),
    ("lib/systemd-ownership.py", "/usr/local/lib/lfcs/systemd-ownership.py"),
    ("lib/ssh-ownership.py", "/usr/local/lib/lfcs/ssh-ownership.py"),
    ("lib/nbd-ownership.py", "/usr/local/lib/lfcs/nbd-ownership.py"),
    ("lib/scenario-engine.sh", "/usr/local/lib/lfcs/scenario-engine.sh"),
    ("lib/extended-engine.py", "/usr/local/lib/lfcs/extended-engine.py"),
)
SPECIAL_RUNTIME_SCRIPTS = (
    ("lib/special-engine.py", "/usr/local/lib/lfcs/special-engine.py"),
)

def run(args, *, check=True, capture=False, input=None, quiet=False, timeout=None):
    # Windows text-mode pipes insert CRLF into scripts destined for Linux.
    binary = os.name == "nt"
    try:
        p = subprocess.run(args, text=not binary,
            input=input.encode("utf-8") if binary and input is not None else input,
            stdout=subprocess.PIPE if capture or quiet else None,
            stderr=subprocess.PIPE if capture or quiet else None, timeout=timeout)
    except FileNotFoundError:
        raise SystemExit(f"Missing command {args[0]!r}. See the platform installation guide.")
    if binary:
        for stream in ("stdout", "stderr"):
            value = getattr(p, stream)
            if value is not None:
                setattr(p, stream, value.decode("utf-8", errors="replace"))
    if check and p.returncode:
        if (quiet or capture) and p.stderr:
            print(p.stderr.strip(), file=sys.stderr)
        raise SystemExit(p.returncode)
    return p

def lima(*args, **kw):
    if redirected(LIMA_HOME) or not LIMA_HOME.resolve().is_relative_to(ROOT):
        raise SystemExit("Refusing redirected candidate Lima home")
    config_dir = LIMA_HOME / "_config"
    for path in (config_dir, LIMA_HOME / "_templates", LIMA_HOME / "_networks",
                 LIMA_HOME / "_disks", config_dir / "user", config_dir / "user.pub"):
        if redirected(path):
            raise SystemExit(f"Refusing redirected Lima path: {path}")
    for name in (INSTANCE, SPECIAL_INSTANCE):
        instance = LIMA_HOME / name
        for path in (instance, instance / "lima.yaml", instance / "disk",
                     instance / "basedisk", instance / "diffdisk", instance / "cidata.iso"):
            if redirected(path):
                raise SystemExit(f"Refusing redirected Lima path: {path}")
    for path in (config_dir / 'default.yaml', config_dir / 'override.yaml',
                 config_dir / 'base.yaml', LIMA_HOME / '_templates/_default/mounts.yaml'):
        if path.exists() or redirected(path):
            raise SystemExit(f"Refusing Lima configuration that can alter guest mounts: {path}")
    if args[0] in {"create", "start", "stop", "delete"}:
        # A default networks.yaml can enumerate and reconcile system-wide networks.
        config_dir.mkdir(parents=True, exist_ok=True)
        networks = config_dir / "networks.yaml"
        if redirected(networks):
            raise SystemExit("Refusing redirected Lima network configuration")
        try:
            with networks.open("x", encoding="utf-8") as stream:
                stream.write("networks: {}\n")
        except FileExistsError:
            if networks.read_text(encoding="utf-8").strip() != "networks: {}":
                raise SystemExit("Refusing custom Lima networks. Use a fresh checkout for the simulator.")
    return run(["limactl", *args], **kw)

def vm_config(name):
    host, arch = host_kind()
    if host == "wsl1": raise SystemExit("WSL1 cannot run the isolated LFCS guest. Upgrade to WSL2.")
    if host not in {"macos", "linux", "wsl2", "windows"} or arch not in {"arm64", "amd64"} or (host == "windows" and arch != "amd64"):
        raise SystemExit(f"No LFCS VM configuration for {host}/{arch}.")
    suffix = "" if host == "macos" and arch == "arm64" else f"-{arch}-{host}"
    stem = "lfcs-special" if name == SPECIAL_INSTANCE else "lfcs"
    config = ROOT / "lima" / f"{stem}{suffix}.yaml"
    if redirected(config) or not config.resolve().is_relative_to(ROOT) or not config.is_file():
        raise SystemExit(f"Missing or redirected VM configuration: {config.name}")
    return config

def create_instance(name):
    config = vm_config(name)
    args = ("create", "--name", name, "--mount-none", "--tty=false")
    if host_kind()[0] == "windows":
        lima(*args, "-", input=config.read_text(encoding="utf-8"))
    else:
        lima(*args, str(config))
    record_owned(name)

def owned_names():
    if redirected(OWNERSHIP):
        raise SystemExit("Refusing symlinked VM ownership record")
    try:
        data = json.loads(OWNERSHIP.read_text(encoding="utf-8"))
        if data.get("root") == str(ROOT): return set(data.get("instances", []))
    except (OSError, ValueError, TypeError): pass
    return set()

def require_owned(name):
    if name not in {INSTANCE, SPECIAL_INSTANCE} or name not in owned_names():
        raise SystemExit(f"Refusing to operate on unowned Lima instance {name!r}. See docs/troubleshooting.md.")

def record_owned(name):
    if name not in {INSTANCE, SPECIAL_INSTANCE}:
        raise SystemExit(f"Refusing to record unexpected Lima instance {name!r}")
    if redirected(OWNERSHIP) or redirected(OWNERSHIP.with_suffix(".tmp")):
        raise SystemExit("Refusing symlinked VM ownership record")
    STATE.mkdir(exist_ok=True)
    names = owned_names() | {name}
    temp = OWNERSHIP.with_suffix(".tmp")
    temp.write_text(json.dumps({"root": str(ROOT), "instances": sorted(names)}, indent=2) + "\n")
    temp.replace(OWNERSHIP)

def forget_owned(name):
    if name not in {INSTANCE, SPECIAL_INSTANCE}:
        raise SystemExit(f"Refusing to remove unexpected Lima instance {name!r}")
    if redirected(OWNERSHIP) or redirected(OWNERSHIP.with_suffix(".tmp")):
        raise SystemExit("Refusing symlinked VM ownership record")
    names = owned_names() - {name}
    temp = OWNERSHIP.with_suffix(".tmp")
    temp.write_text(json.dumps({"root": str(ROOT), "instances": sorted(names)}, indent=2) + "\n")
    temp.replace(OWNERSHIP)

def preflight():
    host, arch = host_kind()
    failures = []
    def report(ok, label, remedy):
        print(f"{'PASS' if ok else 'FAIL'}: {label}" + ("" if ok else f" - {remedy}"))
        if not ok: failures.append(label)
    valid_host = host in {"macos", "linux", "wsl2", "windows"}
    valid_arch = arch in {"amd64", "arm64"} and (host != "windows" or arch == "amd64")
    report(valid_host, f"host {host}", "Use macOS, Linux, or native Windows 11")
    report(valid_arch, f"CPU {arch}", "Use x86_64 on Windows, or x86_64/ARM64 on macOS and Linux")
    report(not redirected(LIMA_HOME), "isolated Lima home", "Use a real checkout-local .lima directory")
    if not valid_host or not valid_arch:
        return False
    if host == "windows":
        report(sys.getwindowsversion().build >= 22000, "Windows 11", "Use Windows 11 x86_64")
        report(windows_local_ntfs(ROOT), "local NTFS checkout", "Use a private local NTFS directory")
    try:
        vm_config(INSTANCE)
        vm_config(SPECIAL_INSTANCE)
    except SystemExit as exc:
        report(False, "guest configurations", str(exc))
    else:
        report(True, "guest configurations", "")
    lima_path = shutil.which("limactl")
    minimum = (2, 3, 0) if host == "windows" else (2, 0, 0) if (host, arch) == ("macos", "arm64") else (2, 1, 3)
    version = None
    if lima_path:
        result = run([lima_path, "--version"], check=False, capture=True)
        if result.returncode == 0:
            version = version_from(result.stdout)
    report(version is not None and version >= minimum, f"Lima version {version_label(version)}",
           f"Install Lima {version_label(minimum)} or newer using the platform guide")
    ssh_tools = [shutil.which(tool) for tool in ("ssh", "scp", "ssh-keygen")]
    if host == "windows":
        ssh_dir = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH")
        report(all(path and pathlib.Path(path).resolve().parent == ssh_dir.resolve() for path in ssh_tools),
               "native Windows OpenSSH client tools", "Put Windows OpenSSH Client ahead of Git/MSYS on PATH")
    else:
        for name, path in zip(("ssh", "scp", "ssh-keygen"), ssh_tools):
            report(path is not None, name, "Install the OpenSSH client tools")
    if (host, arch) != ("macos", "arm64"):
        qemu = "qemu-system-aarch64" if arch == "arm64" else "qemu-system-x86_64"
        qemu_path = shutil.which(qemu)
        qemu_minimum = {"windows": (11, 0, 0), "macos": (8, 2, 1)}.get(host, (6, 2, 0))
        qemu_version = None
        if qemu_path:
            result = run([qemu_path, "--version"], check=False, capture=True)
            if result.returncode == 0:
                qemu_version = version_from(result.stdout)
        report(qemu_version is not None and qemu_version >= qemu_minimum,
               f"{qemu} version {version_label(qemu_version)}",
               f"Install QEMU {version_label(qemu_minimum)} or newer")
        report(shutil.which("qemu-img") is not None, "qemu-img", "Install the QEMU disk tools")
        if host == "windows":
            result = run([qemu_path, "-accel", "help"], check=False, capture=True) if qemu_path else None
            report(result is not None and result.returncode == 0 and
                   "whpx" in (result.stdout + result.stderr).lower().split(),
                   "QEMU WHPX accelerator", "Install a native Windows QEMU build with WHPX")
            report(windows_hypervisor(), "Windows Hypervisor Platform",
                   "Check firmware virtualization and ask an administrator to enable Windows Hypervisor Platform")
    if host in {"linux", "wsl2"}:
        report(kvm_access(), "KVM acceleration", "Enable virtualization and grant your user access to /dev/kvm")
        if host == "wsl2":
            report(not str(ROOT).startswith("/mnt/"), "WSL Linux filesystem",
                   "Clone under your WSL home directory")
    if host == "macos":
        result = run(["sysctl", "-n", "kern.hv_support"], check=False, capture=True)
        report(result.returncode == 0 and result.stdout.strip() == "1", "macOS hardware virtualization",
               "Use a Mac with hardware virtualization available")
    free = shutil.disk_usage(ROOT).free
    report(free >= 12 * 1024**3, f"disk free {free // 1024**3} GiB", "Free at least 12 GiB for both guests")
    ram, available = host_memory(host)
    report(ram >= 6 * 1024**3, f"host RAM {ram // 1024**3} GiB", "At least 6 GiB is required")
    if available is not None:
        report(available >= 2 * 1024**3, f"available RAM {available / 1024**3:.1f} GiB",
               "Free at least 2 GiB before starting a guest")
    if not failures:
        for name in (INSTANCE, SPECIAL_INSTANCE):
            if instance_info(name):
                report(name in owned_names(), f"instance {name} ownership",
                       "Existing instance is not owned by this checkout")
    print("Preflight checks only; a live lab acceptance test is still required.")
    return not failures

def cmd_doctor(args):
    if not preflight(): raise SystemExit(1)

def cmd_setup(args):
    cmd_doctor([])
    print("Prerequisites are present. Run ./bin/lfcs start to create the isolated guest.")

def instance_info(name=INSTANCE):
    if not LIMA_HOME.exists():
        return None
    p = lima("list", "--json", capture=True)
    for line in filter(str.strip, p.stdout.splitlines()):
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            raise SystemExit("Lima returned an invalid instance inventory")
        if not isinstance(v, dict) or not isinstance(v.get("name"), str):
            raise SystemExit("Lima returned an invalid instance inventory")
        if v["name"] == name:
            return v
    return None

def require_running(name=INSTANCE):
    require_owned(name)
    info = instance_info(name)
    if not info or info.get("status") != "Running":
        command = "./bin/lfcs start" if name == INSTANCE else f"./bin/lfcs start {name}"
        print(f"LFCS host {name} is not running. Start it with: {command}", file=sys.stderr)
        raise SystemExit(2)

def guest(command, *, instance=INSTANCE, input=None, capture=False, check=True, quiet=False):
    require_owned(instance)
    return lima("shell", instance, "--", "sudo", "bash", "-lc", command,
                input=input, capture=capture, check=check, quiet=quiet)

def du_kb(path):
    if os.name == "nt":
        return windows_allocated_kb(path)
    p = run(["du", "-sk", str(path)], check=False, capture=True)
    try: return int(p.stdout.split()[0])
    except (IndexError, ValueError): return 0

def save_baseline():
    STATE.mkdir(exist_ok=True)
    if redirected(BASELINE):
        raise SystemExit("Refusing symlinked storage baseline")
    if BASELINE.exists(): return
    data = {"created": datetime.now(timezone.utc).isoformat(),
            "lima_kb": du_kb(LIMA_HOME),
            "cache_kb": 0}
    BASELINE.write_text(json.dumps(data, indent=2) + "\n")

def allocated_kb():
    inst = du_kb(LIMA_HOME / INSTANCE)
    project = max(0, du_kb(ROOT) - du_kb(LIMA_HOME))
    cache_delta = 0
    if redirected(BASELINE):
        raise SystemExit("Refusing symlinked storage baseline")
    return inst, cache_delta, project

def budget_guard(stop=False):
    inst, cache, project = allocated_kb()
    total = inst + cache + project
    if total >= 4 * 1024 * 1024:
        if stop and instance_info() and instance_info().get("status") == "Running":
            require_owned(INSTANCE)
            lima("stop", INSTANCE, check=False)
        if stop:
            print("ERROR: LFCS allocation reached the 4.00 GB hard target; the VM was stopped.", file=sys.stderr)
            raise SystemExit(3)
        print("WARNING: Existing LFCS allocation is above 4.00 GB; run ./bin/lfcs cleanup when convenient.", file=sys.stderr)
        return
    if total >= int(3.5 * 1024 * 1024):
        print("WARNING: LFCS allocation is above the preferred 3.50 GB target.", file=sys.stderr)

def install_script(local, remote, *, instance=INSTANCE):
    content = (ROOT / local).read_text(encoding="utf-8")
    guest(f"install -d {pathlib.PurePosixPath(remote).parent}; cat > {remote}; chmod 0755 {remote}", instance=instance, input=content)

def sync_runtime_scripts():
    """Keep an existing VM compatible with the current host-side engines."""
    host_access, *engines = RUNTIME_SCRIPTS
    install_script(*host_access)
    guest("/usr/local/lib/lfcs/ensure-host-access.sh --hostname-only")
    for local, remote in engines:
        install_script(local, remote)

def mark_guest(instance):
    """Bind the guest guard to this VM's machine ID and a fresh random key."""
    machine_id = guest("cat /etc/machine-id", instance=instance, capture=True).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{32}", machine_id):
        raise SystemExit("Refusing guest without a valid machine ID")
    key = secrets.token_bytes(32)
    message = f"lfcs-release-candidate-v2:{instance}:{machine_id}"
    marker = f"{message}:{hmac.new(key, message.encode(), hashlib.sha256).hexdigest()}\n"
    verifier = (ROOT / "lib/verify-guest.py").read_text(encoding="utf-8").replace("__LFCS_GUEST_KEY__", key.hex())
    if "__LFCS_GUEST_KEY__" in verifier:
        raise SystemExit("Guest verifier key substitution failed")
    guest("install -d -o root -g root -m 0700 /etc/lfcs-release-candidate; "
          "install -d -o root -g root -m 0755 /usr/local/lib/lfcs; "
          "cat > /usr/local/lib/lfcs/verify-guest.py; "
          "chown root:root /usr/local/lib/lfcs/verify-guest.py; chmod 0500 /usr/local/lib/lfcs/verify-guest.py",
          instance=instance, input=verifier)
    guest("cat > /etc/lfcs-release-candidate/identity; "
          "chown root:root /etc/lfcs-release-candidate/identity; chmod 0600 /etc/lfcs-release-candidate/identity; "
          "/usr/local/lib/lfcs/verify-guest.py",
          instance=instance, input=marker)

def sync_special_runtime_scripts():
    for local, remote in SPECIAL_RUNTIME_SCRIPTS:
        install_script(local, remote, instance=SPECIAL_INSTANCE)

def ensure_special_started(*, require_health=True):
    """Create, start, and idempotently provision the SELinux-native host."""
    if not preflight(): raise SystemExit("Preflight failed; special VM creation stopped.")
    if not shutil.which("limactl"):
        raise SystemExit("Lima is missing. Install it with: brew install lima")
    info = instance_info(SPECIAL_INSTANCE)
    if info: require_owned(SPECIAL_INSTANCE)
    if not info:
        free_kb = shutil.disk_usage(ROOT).free // 1024
        if free_kb < 6 * 1024 * 1024:
            raise SystemExit("At least 6 GB free host space is required to create lfcs-special safely.")
        print("Creating LFCS Fedora special host (logical disk is sparse)...")
        create_instance(SPECIAL_INSTANCE)
        info = instance_info(SPECIAL_INSTANCE)
    if info.get("status") != "Running":
        lima("start", "--mount-none", "--tty=false", SPECIAL_INSTANCE)
    mark_guest(SPECIAL_INSTANCE)
    marker = guest("test -f /var/lib/lfcs-special/provisioned-v1", instance=SPECIAL_INSTANCE,
                   check=False, quiet=True).returncode == 0
    if not marker:
        print("Provisioning the SELinux and directory-services practice host...")
        guest("bash -s", instance=SPECIAL_INSTANCE, input=(ROOT / "provisioning/special.sh").read_text(encoding="utf-8"))
    sync_special_runtime_scripts()
    ensure_student_admin(instance=SPECIAL_INSTANCE)
    if require_health:
        health = guest("/usr/local/lib/lfcs/special-engine.py health all", instance=SPECIAL_INSTANCE,
                       check=False, capture=True)
        if health.returncode or "FAIL|" in health.stdout:
            if health.stdout.strip(): print(health.stdout.rstrip(), file=sys.stderr)
            raise SystemExit("lfcs-special failed its baseline health check")
        return health
    return None

def ensure_student_admin(*, instance=INSTANCE):
    """Restore infrastructure-owned student access without touching exercise rules."""
    guest(
        f"id student >/dev/null 2>&1; "
        f"install -d -m 0750 /etc/sudoers.d; "
        f"cat > {STUDENT_SUDOERS}; chmod 0440 {STUDENT_SUDOERS}; "
        f"rm -f /etc/sudoers.d/90-lfcs-student; "
        f"visudo -cf {STUDENT_SUDOERS} >/dev/null",
        input="student ALL=(ALL) NOPASSWD: ALL\n", instance=instance,
    )

def ensure_host_access():
    """Keep Lima's management SSH listener separate from SSH exercises."""
    guest("/usr/local/lib/lfcs/ensure-host-access.sh")

def cmd_start(args):
    if args and (len(args) != 1 or args[0] not in {SPECIAL_HOST, SPECIAL_INSTANCE, "special", INSTANCE, "lfcs", "main"}):
        raise SystemExit("Usage: lfcs start [lfcs-special]")
    if not preflight(): raise SystemExit("Preflight failed; VM creation stopped.")
    if args and args[0] in (SPECIAL_HOST, SPECIAL_INSTANCE, "special"):
        ensure_special_started()
        print("LFCS special host is ready. Try: ./bin/lfcs list special")
        return
    if not shutil.which("limactl"):
        raise SystemExit("Lima is missing. Install it with: brew install lima")
    save_baseline()
    info = instance_info()
    if info: require_owned(INSTANCE)
    created = info is None
    if not info:
        free_kb = shutil.disk_usage(ROOT).free // 1024
        if free_kb < 5 * 1024 * 1024:
            raise SystemExit("At least 5 GB free host space is required to create the capped lab safely.")
        print("Creating LFCS Ubuntu 24.04 Minimal VM (logical disk is sparse)...")
        create_instance(INSTANCE)
    if instance_info().get("status") != "Running":
        lima("start", "--mount-none", "--tty=false", INSTANCE)
    if created: budget_guard(stop=True)
    mark_guest(INSTANCE)
    sync_runtime_scripts()
    ensure_host_access()
    install_script("tests/guest-regression-solutions.sh", "/usr/local/lib/lfcs/guest-regression-solutions.sh")
    marker = guest("test -f /var/lib/lfcs-lab/provisioned-v1", check=False, quiet=True).returncode == 0
    if not marker:
        print("Provisioning compact LFCS package set...")
        guest("bash -s", input=(ROOT / "provisioning/common.sh").read_text(encoding="utf-8"))
        budget_guard(stop=created)
        guest("bash -s", input=(ROOT / "provisioning/services.sh").read_text(encoding="utf-8"))
    ensure_student_admin()
    marker2 = guest("test -f /var/lib/lfcs-lab/provisioned-v2", check=False, quiet=True).returncode == 0
    if not marker2:
        print("Adding Docker, iptables persistence, manuals, build, time, and virtualization tools...")
        guest("bash -s", input=(ROOT / "provisioning/upgrade-v2.sh").read_text(encoding="utf-8"))
    persistence_tools = guest("command -v netfilter-persistent >/dev/null", check=False, quiet=True).returncode == 0
    if not persistence_tools:
        print("Restoring missing iptables persistence runtime...")
        guest("export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; "
              "apt-get install -y --no-install-recommends iptables-persistent netfilter-persistent >/dev/null")
    nm_managed = guest("grep -qx 'unmanaged-devices=none' /etc/NetworkManager/conf.d/90-lfcs-managed.conf", check=False, quiet=True).returncode == 0
    if not nm_managed:
        guest("install -d /etc/NetworkManager/conf.d; printf '[keyfile]\\nunmanaged-devices=none\\n' >/etc/NetworkManager/conf.d/90-lfcs-managed.conf; systemctl restart NetworkManager")
    topology = guest("ip netns list | grep -qw node1 && ip netns list | grep -qw router1", check=False, quiet=True).returncode == 0
    disks = guest("test -b /dev/lfcs-disk1 && test -b /dev/lfcs-disk2 && test -b /dev/lfcs-disk3", check=False, quiet=True).returncode == 0
    if not topology:
        print("Initializing missing simulated topology..."); guest("/usr/local/lib/lfcs/topology.sh reset")
    if not disks:
        print("Initializing missing sparse practice disks..."); guest("/usr/local/lib/lfcs/storage.sh reset-all")
    if topology and disks: print("Existing topology and practice-disk state preserved.")
    budget_guard(stop=created)
    print("LFCS lab is ready. Try: ./bin/lfcs day 1")
    cmd_disk_usage([])

def cmd_stop(args):
    if args and (len(args) != 1 or args[0] not in {SPECIAL_HOST, SPECIAL_INSTANCE, "special", INSTANCE, "lfcs", "main"}):
        raise SystemExit("Usage: lfcs stop [lfcs-special]")
    if args and args[0] in (SPECIAL_HOST, SPECIAL_INSTANCE, "special"):
        info = instance_info(SPECIAL_INSTANCE)
        if info: require_owned(SPECIAL_INSTANCE)
        if info and info.get("status") == "Running": lima("stop", SPECIAL_INSTANCE)
        else: print("LFCS special host is already stopped or absent.")
        return
    info = instance_info()
    if info: require_owned(INSTANCE)
    if info and info.get("status") == "Running":
        ensure_host_access()
        lima("stop", INSTANCE)
    else: print("LFCS VM is already stopped or absent.")

def cmd_status(args):
    info = instance_info()
    print("Linux Admin Practice Lab status")
    print(f"VM:          {info.get('status') if info else 'Not created'}")
    if info and info.get("status") == "Running":
        require_owned(INSTANCE)
        try:
            management = lima("shell", INSTANCE, "--", "true", check=False, capture=True, timeout=10)
        except subprocess.TimeoutExpired:
            management = None
        if management is None or management.returncode:
            detail = "timed out" if management is None else f"exit {management.returncode}"
            print(f"Management:  UNAVAILABLE ({detail})")
            print("Health:      UNHEALTHY (Lima process state is not sufficient)")
            raise SystemExit(4)
        print("Management:  ready")
        p = guest("for n in node1 node2 node3 router1; do ip netns list | awk '{print $1}' | grep -qx $n && echo $n; done | paste -sd, -", capture=True, check=False)
        print(f"Namespaces:  {p.stdout.strip() or 'not initialized'}")
        p = guest("systemctl is-system-running", capture=True, check=False)
        print(f"systemd:     {p.stdout.strip()}")
        if p.returncode or p.stdout.strip() not in {"running", "degraded"}:
            print("Health:      UNHEALTHY")
            raise SystemExit(5)
    special = instance_info(SPECIAL_INSTANCE)
    print(f"Special VM:  {special.get('status') if special else 'Not created'}")
    if special and special.get("status") == "Running":
        require_owned(SPECIAL_INSTANCE)
        result = guest("/usr/local/lib/lfcs/special-engine.py health all", instance=SPECIAL_INSTANCE,
                       capture=True, check=False)
        failures = [line for line in result.stdout.splitlines() if line.startswith("FAIL|")]
        print(f"Special:     {'healthy' if result.returncode == 0 and not failures else 'UNHEALTHY'}")

def fmt_kb(kb):
    if kb >= 1024 * 1024: return f"{kb/1024/1024:.2f} GB"
    return f"{kb/1024:.0f} MB"

def cmd_disk_usage(args):
    inst, cache, project = allocated_kb()
    docker = podman = loops_actual = loops_apparent = 0
    if instance_info() and instance_info().get("status") == "Running":
        p = guest("du -sk /var/lib/docker /var/lib/containerd 2>/dev/null | awk '{s+=$1} END{print s}'", capture=True, check=False)
        try: docker = int(p.stdout.strip())
        except ValueError: pass
        p = guest("du -sk /var/lib/containers 2>/dev/null | awk '{print $1}'", capture=True, check=False)
        try: podman = int(p.stdout.strip())
        except ValueError: pass
        p = guest("du -sk /var/lib/lfcs-disks 2>/dev/null | awk '{print $1}'", capture=True, check=False)
        try: loops_actual = int(p.stdout.strip())
        except ValueError: pass
        p = guest("du -sk --apparent-size /var/lib/lfcs-disks 2>/dev/null | awk '{print $1}'", capture=True, check=False)
        try: loops_apparent = int(p.stdout.strip())
        except ValueError: pass
    total = inst + cache + project
    print("Linux Admin Practice Lab storage\n")
    print(f"Lima instance:       {fmt_kb(inst):>10}")
    print(f"New Lima cache:      {fmt_kb(cache):>10}")
    print(f"Project files:       {fmt_kb(project):>10}")
    print(f"Docker storage*:     {fmt_kb(docker):>10}")
    print(f"Preserved Podman*:   {fmt_kb(podman):>10}")
    print(f"Practice disks*:     {fmt_kb(loops_actual):>10} actual / {fmt_kb(loops_apparent)} apparent")
    print(f"\nApproximate added:  {fmt_kb(total):>10}")
    print("Budget:               4.00 GB")
    print(f"Remaining:            {fmt_kb(max(0, 4*1024*1024-total))}")
    print("\n* Included inside the Lima instance total; practice disks are sparse.")

def cmd_list(args):
    rows = LABS
    if args:
        q = args[0].lower()
        if q.startswith("day"): q = q[3:]
        if q.isdigit(): rows = [x for x in rows if x["day"] == int(q)]
        elif q in {"special", SPECIAL_HOST, SPECIAL_INSTANCE}: rows = [x for x in rows if x["host"] == SPECIAL_HOST]
        else: rows = [x for x in rows if x["domain"] == q]
    print(f"{'ID':<18} {'DAY':<3} {'DOMAIN':<11} {'HOST':<12} {'MIN':>3}  TITLE")
    for x in rows: print(f"{x['id']:<18} {x['day']:<3} {x['domain']:<11} {x['host']:<12} {x['minutes']:>3}  {x['title']}")
    print(f"\n{len(rows)} lab(s)")

def engine(mode, id, capture=False):
    if BY_ID[id]["host"] == SPECIAL_HOST:
        # A staged repair task may intentionally make canonical health fail
        # (ldap-04 stops the directory provider).  Scenario operations require
        # a runnable/provisioned host, not a clean-baseline precondition.
        ensure_special_started(require_health=False)
        return guest(f"/usr/local/lib/lfcs/special-engine.py {mode} {id}",
                     instance=SPECIAL_INSTANCE, capture=capture)
    require_running()
    sync_runtime_scripts()
    return guest(f"/usr/local/lib/lfcs/scenario-engine.sh {mode} {id}", capture=capture)

def parse_grade_output(output):
    results=[]
    for line in output.splitlines():
        if "|" in line and line.split("|",1)[0] in ("PASS","FAIL"):
            results.append(tuple(line.split("|",1)))
    return results

def inspect_grade(id):
    return parse_grade_output(engine("grade", id, capture=True).stdout)

def progress_data():
    if not PROGRESS.resolve().is_relative_to(ROOT) or redirected(PROGRESS):
        raise SystemExit("Refusing progress path outside the candidate or through a symlink")
    try: return json.loads(PROGRESS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError): return {"labs": {}, "mistakes": []}

def save_progress(d):
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    if not PROGRESS.resolve().is_relative_to(ROOT) or redirected(PROGRESS):
        raise SystemExit("Refusing progress path outside the candidate or through a symlink")
    PROGRESS.write_text(json.dumps(d, indent=2) + "\n")

def show_task(x):
    print(f"\nLFCS PRACTICE TASK: {x['id']}\n\n{x['title']}\n\nHost: {x['host']}\n\nConfigure the system so that:\n")
    for r in x["requirements"]: print(f"- {r}")
    print(f"\nSuggested time: {x['minutes']} minutes")
    if x["host"] in NAMESPACES or x["host"] == SPECIAL_HOST:
        print(f"Enter host: ./bin/lfcs shell {x['host']}")
    else: print("Enter host: ./bin/lfcs shell")

def scenario_instance(id):
    return SPECIAL_INSTANCE if BY_ID[id]["host"] == SPECIAL_HOST else INSTANCE

def ensure_topology():
    """Repair missing namespace infrastructure before staging a fresh task."""
    require_running()
    probe = guest("for n in node1 node2 node3 router1; do ip netns list | awk '{print $1}' | grep -qx \"$n\" || exit 1; done; ip netns exec node1 ping -c1 -W1 10.10.2.10 >/dev/null", check=False, quiet=True)
    if probe.returncode:
        print("Restoring missing LFCS network topology before task setup...")
        guest("/usr/local/lib/lfcs/topology.sh reset")
        verified = guest("for n in node1 node2 node3 router1; do ip netns list | awk '{print $1}' | grep -qx \"$n\" || exit 1; done; ip netns exec node1 ping -c1 -W1 10.10.2.10 >/dev/null", check=False, quiet=True)
        if verified.returncode: raise SystemExit("LFCS topology recovery failed; task was not staged")

def stage_id(id, *, started=None):
    """Stage one task and record its final-state rubric before learner work."""
    target = scenario_instance(id)
    if target == SPECIAL_INSTANCE:
        ensure_special_started(require_health=False)
    else:
        ensure_topology()
    ensure_student_admin(instance=target)
    engine("setup", id)
    ensure_student_admin(instance=target)
    baseline=inspect_grade(id)
    passed=sum(1 for status,_ in baseline if status=="PASS")
    d=progress_data(); rec=d["labs"].setdefault(id,{})
    rec.update(
        started=time.time() if started is None else started,
        hints_current=0,
        baseline_checks={message:status for status,message in baseline},
        baseline_score=round(100*passed/len(baseline)) if baseline else 0,
        baseline_captured=datetime.now(timezone.utc).isoformat(),
    )
    save_progress(d)
    return baseline

def cmd_lab(args):
    if not args or args[0] not in BY_ID: raise SystemExit("Usage: ./bin/lfcs lab SCENARIO_ID")
    x = BY_ID[args[0]]
    print(f"Preparing {x['id']}...")
    stage_id(x["id"])
    show_task(x)

def cmd_reset(args):
    if not args or args[0] not in BY_ID: raise SystemExit("Usage: ./bin/lfcs reset SCENARIO_ID")
    stage_id(args[0])
    print(f"{args[0]} restored to its starting state.")

def cmd_hint(args):
    if not args or args[0] not in BY_ID: raise SystemExit("Usage: ./bin/lfcs hint SCENARIO_ID")
    id=args[0]; d=progress_data(); rec=d["labs"].setdefault(id, {}); n=min(int(rec.get("hints_current",0))+1, len(BY_ID[id]["hints"])); rec["hints_current"]=n; rec["hints_used"]=int(rec.get("hints_used",0))+1; save_progress(d)
    print(f"Hint {n}:\n{BY_ID[id]['hints'][n-1]}")

def category(msg):
    s=msg.lower()
    if any(w in s for w in ("syntax","validates","well formed","parses")): return "SYNTAX"
    if any(w in s for w in ("persistent","enabled","fstab","boot")): return "PERSISTENCE"
    if any(w in s for w in ("reaches","response","connect","active","mounted","running")): return "VALIDATION"
    if any(w in s for w in ("route","gateway","firewall","source","configuration","correct")): return "TROUBLESHOOTING"
    return "KNOWLEDGE"

PRACTICE_SCORE_NOTICE = (
    "Simulator scores do not represent official Linux Foundation certification "
    "results or predict exam outcomes."
)


def grade_id(id, display=True):
    results=inspect_grade(id)
    passed=sum(1 for s,_ in results if s=="PASS"); score=round(100*passed/len(results)) if results else 0
    d=progress_data(); rec=d["labs"].setdefault(id,{})
    if display:
        for s,m in results: print(f"[{s}] {m}")
        baseline=rec.get("baseline_checks")
        if isinstance(baseline,dict) and baseline:
            baseline_passed=sum(1 for value in baseline.values() if value=="PASS")
            comparable=[(status,message) for status,message in results if message in baseline]
            improved=[message for status,message in comparable if status=="PASS" and baseline[message]=="FAIL"]
            regressed=[message for status,message in comparable if status=="FAIL" and baseline[message]=="PASS"]
            baseline_score=round(100*baseline_passed/len(baseline))
            delta=score-baseline_score
            print(f"\nBaseline: {baseline_score}% ({baseline_passed}/{len(baseline)} checks already satisfied)")
            print(f"Final: {score}% ({passed}/{len(results)} checks satisfied)")
            print(f"Improvement: {delta:+d} percentage points; {len(improved)} newly passed; {len(regressed)} regressed")
        else:
            print("\nBaseline: unavailable (restage this scenario to capture it)")
            print(f"Final: {score}% ({passed}/{len(results)} checks satisfied)")
        print(f"Practice final-state score: {score}%")
        print(f"Score: {score}%")
        print(PRACTICE_SCORE_NOTICE)
    elapsed=max(0,int(time.time()-float(rec.get("started",time.time())))); rec["attempts"]=int(rec.get("attempts",0))+1; rec["latest_score"]=score; rec["latest_seconds"]=elapsed
    if score>=int(rec.get("best_score",-1)): rec["best_score"]=score; rec["best_seconds"]=elapsed
    for s,m in results:
        if s=="FAIL":
            reason = "COMMAND RECALL" if int(rec.get("hints_current",0)) >= 2 and category(m)=="KNOWLEDGE" else category(m)
            d["mistakes"].append({"time":datetime.now(timezone.utc).isoformat(),"scenario":id,"category":reason,"requirement":m})
    if elapsed > BY_ID[id]["minutes"]*60 and score < 80:
        d["mistakes"].append({"time":datetime.now(timezone.utc).isoformat(),"scenario":id,"category":"TIME","requirement":"Exceeded suggested time below 80%"})
    save_progress(d); return score

def cmd_grade(args):
    if not args or args[0] not in BY_ID: raise SystemExit("Usage: ./bin/lfcs grade SCENARIO_ID")
    grade_id(args[0])

def cmd_shell(args):
    if len(args) > 1 or (args and args[0] not in NAMESPACES | {INSTANCE, SPECIAL_INSTANCE, SPECIAL_HOST, "lfcs", "main", "special"}):
        raise SystemExit("Usage: lfcs shell [lfcs|lfcs-special|node1|node2|node3|router1]")
    student_shell = ["sudo","-u","student","-H","sh","-c",'cd "$HOME" && exec bash -l']
    if args and args[0] in (SPECIAL_HOST, SPECIAL_INSTANCE, "special"):
        ensure_special_started(require_health=False)
        return lima("shell", SPECIAL_INSTANCE, "--", *student_shell)
    require_running()
    ensure_student_admin()
    if not args or args[0] in ("lfcs", "main", INSTANCE):
        return lima("shell", INSTANCE, "--", *student_shell)
    ns=args[0]
    if ns not in NAMESPACES: raise SystemExit("Host must be lfcs, lfcs-special, node1, node2, node3, or router1")
    return lima("shell", INSTANCE, "--", "sudo", "ip", "netns", "exec", ns, *student_shell)

def cmd_day(args):
    if not args or args[0] not in {"1","2","3","4","5"}: raise SystemExit("Usage: ./bin/lfcs day 1..5 [start]")
    day=int(args[0]); cmd_list([str(day)])
    first=next(x for x in LABS if x["day"]==day)
    print(f"\nStart with: ./bin/lfcs lab {first['id']}")
    if len(args)>1 and args[1]=="start": cmd_lab([first["id"]])

def cmd_mock(args):
    if not args or args[0] not in MOCKS: raise SystemExit("Usage: ./bin/lfcs mock " + "|".join(MOCKS))
    n=args[0]; require_running(); print(f"Preparing Mock {n}...")
    d=progress_data(); old=d.get("mocks",{}).get(n,{})
    old_idx=int(old.get("index",0))
    if old:
        engine("reset",MOCKS[n][min(old_idx,len(MOCKS[n])-1)]); ensure_student_admin()
    d=progress_data(); d.setdefault("mocks",{})[n]={"started":time.time(),"index":0,"scores":{}}; save_progress(d)
    stage_id(MOCKS[n][0])
    print(f"\nMOCK PRACTICE SESSION {n} — 120 minutes\n")
    for i,id in enumerate(MOCKS[n],1):
        x=BY_ID[id]; print(f"{i}. [{x['host']}] {x['title']}")
        for r in x["requirements"]: print(f"   - {r}")
    print("\nThe compact one-VM runner stages tasks serially so destructive labs cannot overwrite each other.")
    print(f"Current staged task: 1 — {MOCKS[n][0]}")
    print(f"Tasks: {len(MOCKS[n])}")
    print(f"Enter host: ./bin/lfcs shell {BY_ID[MOCKS[n][0]]['host']}")
    print(f"Complete it, then grade and advance with: ./bin/lfcs mock-grade {n}")

def print_exam_score(label, session, ids, limit):
    scores=session.get("scores",{}); vals=[scores.get(i,0) for i in ids]
    raw=round(sum(vals)/len(vals))
    print(f"\n{label} LAB RAW SCORE: {raw}%")
    grouped={}
    for i in ids: grouped.setdefault(BY_ID[i]["domain"],[]).append(scores.get(i,0))
    names={"operations":"Operations & Deployment","networking":"Networking","storage":"Storage","commands":"Essential Commands","users":"Users & Groups","mixed":"Mixed"}
    domain_scores={domain:round(sum(values)/len(values)) for domain,values in grouped.items()}
    for domain,score in domain_scores.items(): print(f"{names.get(domain,domain.title()):<24} {score:>3}%")
    weights={"operations":0.25,"networking":0.25,"storage":0.20,"commands":0.20,"users":0.10}
    if set(weights).issubset(domain_scores):
        weighted=round(sum(domain_scores[domain]*weight for domain,weight in weights.items()))
        print(f"DOMAIN-WEIGHTED PRACTICE SCORE: {weighted}%")
    else:
        print("DOMAIN-WEIGHTED PRACTICE SCORE: UNAVAILABLE (suite does not cover every domain)")
    print(PRACTICE_SCORE_NOTICE)
    print("\nPractice task scores")
    for q,i in enumerate(ids,1): print(f"Q{q:<2} {scores.get(i,0):>3}%  {i}")
    elapsed=int(time.time()-float(session.get("started",time.time())))
    print(f"\nElapsed: {elapsed//60:02}:{elapsed%60:02} / {limit}:00")

def cmd_mock_grade(args):
    if not args or args[0] not in MOCKS: raise SystemExit("Usage: ./bin/lfcs mock-grade " + "|".join(MOCKS))
    n=args[0]; d=progress_data(); session=d.get("mocks",{}).get(n)
    if not session: raise SystemExit(f"Mock {n} is not active. Start it with: ./bin/lfcs mock {n}")
    idx=int(session.get("index",0))
    if idx >= len(MOCKS[n]): raise SystemExit(f"Mock {n} is already complete. Reset it with: ./bin/lfcs mock-reset {n}")
    id=MOCKS[n][idx]; print(f"\nMock {n}, task {idx+1}: {id}"); score=grade_id(id)
    d=progress_data(); session=d.setdefault("mocks",{}).setdefault(n,{})
    session.setdefault("scores",{})[id]=score; session["index"]=idx+1; save_progress(d)
    engine("reset",id); ensure_student_admin()
    if idx+1 < len(MOCKS[n]):
        nxt=MOCKS[n][idx+1]; stage_id(nxt); print(f"\nNext staged task: {idx+2} — {nxt}"); show_task(BY_ID[nxt]); print(f"Grade and advance with: ./bin/lfcs mock-grade {n}")
    else:
        print_exam_score(f"MOCK {n}", session, MOCKS[n], 120)

def cmd_mini(args):
    if not args or args[0] not in MINIS: raise SystemExit("Usage: ./bin/lfcs mini 1|2|3|4|5")
    n=args[0]; require_running(); d=progress_data(); old=d.get("minis",{}).get(n,{})
    old_idx=int(old.get("index",0))
    if old:
        engine("reset",MINIS[n][min(old_idx,len(MINIS[n])-1)]); ensure_student_admin()
    d=progress_data(); d.setdefault("minis",{})[n]={"started":time.time(),"index":0,"scores":{}}; save_progress(d)
    stage_id(MINIS[n][0]); print(f"\nMINI PRACTICE SESSION {n} — 45 minutes\n")
    for q,i in enumerate(MINIS[n],1):
        x=BY_ID[i]; print(f"{q}. [{x['host']}] {x['title']}")
        for req in x["requirements"]: print(f"   - {req}")
    print(f"\nCurrent staged task: 1 — {MINIS[n][0]}")
    print(f"Grade and advance with: ./bin/lfcs mini-grade {n}")

def cmd_mini_grade(args):
    if not args or args[0] not in MINIS: raise SystemExit("Usage: ./bin/lfcs mini-grade 1|2|3|4|5")
    n=args[0]; d=progress_data(); session=d.get("minis",{}).get(n)
    if not session: raise SystemExit(f"Mini {n} is not active. Start it with: ./bin/lfcs mini {n}")
    idx=int(session.get("index",0)); ids=MINIS[n]
    if idx>=len(ids): raise SystemExit(f"Mini {n} is already complete. Restart with: ./bin/lfcs mini {n}")
    sid=ids[idx]; score=grade_id(sid); d=progress_data(); session=d.setdefault("minis",{}).setdefault(n,{})
    session.setdefault("scores",{})[sid]=score; session["index"]=idx+1; save_progress(d)
    engine("reset",sid); ensure_student_admin()
    if idx+1<len(ids):
        nxt=ids[idx+1]; stage_id(nxt); print(f"\nNext staged task: {idx+2} — {nxt}"); show_task(BY_ID[nxt])
    else: print_exam_score(f"MINI {n}",session,ids,45)

def cmd_progress(args):
    d=progress_data(); print(f"{'SCENARIO':<18} {'ATTEMPTS':>8} {'BEST':>6} {'TIME':>7} {'LATEST':>7} {'HINTS':>6}")
    for id,r in sorted(d["labs"].items()):
        sec=int(r.get("best_seconds",0)); print(f"{id:<18} {int(r.get('attempts',0)):>8} {str(r.get('best_score','-'))+'%':>6} {sec//60:02}:{sec%60:02} {str(r.get('latest_score','-'))+'%':>7} {int(r.get('hints_used',0)):>6}")

def cmd_mistakes(args):
    d=progress_data(); rows=d.get("mistakes",[])
    if not rows: print("No graded mistakes recorded yet."); return
    for r in rows[-50:]: print(f"{r['scenario']:<18} {r['category']:<16} {r['requirement']}")

def cmd_weaknesses(args):
    d=progress_data(); names={"operations":"OPERATIONS & DEPLOYMENT","networking":"NETWORKING","storage":"STORAGE","commands":"ESSENTIAL COMMANDS","users":"USERS & GROUPS"}
    recommendations=[]
    for domain in ("operations","networking","storage","commands","users"):
        print(f"\n{names[domain]}\n")
        skills={}
        for x in LABS:
            if x["domain"]!=domain: continue
            score=d.get("labs",{}).get(x["id"],{}).get("best_score")
            for skill in x.get("skills",[x["title"].lower()]): skills.setdefault(skill,[]).append(score)
        ranked=[]
        for skill,scores in skills.items():
            attempted=[v for v in scores if v is not None]
            avg=round(sum(attempted)/len(attempted)) if attempted else 0
            level="STRONG" if attempted and avg>=85 else ("MEDIUM" if attempted and avg>=65 else "WEAK")
            ranked.append((0 if level=="WEAK" else 1 if level=="MEDIUM" else 2,avg,skill,level))
        for _,avg,skill,level in sorted(ranked)[:12]: print(f"{skill:<32} {level:<6} {avg if avg else '-'}")
        for _,_,skill,level in sorted(ranked):
            if level=="WEAK":
                candidate=next((x["id"] for x in LABS if x["domain"]==domain and skill in x.get("skills",[]) and d.get("labs",{}).get(x["id"],{}).get("best_score",0)<80),None)
                if candidate: recommendations.append(candidate); break
    print("\nPRACTISE NEXT\n" + "\n".join(f"- {x}" for x in recommendations[:5]))

def cmd_solution(args):
    if not args or args[0] not in BY_ID: raise SystemExit("Usage: ./bin/lfcs solution SCENARIO_ID")
    print(f"REFERENCE SOLUTION — {args[0]}\n")
    print(solution_for(args[0]))

def cmd_reset_all(args):
    require_running()
    print("This restores all LFCS-owned topology, practice disks, and scenario state. Progress is retained.")
    if "--yes" not in args and input("Type RESET-LFCS to continue: ").strip()!="RESET-LFCS": print("Cancelled."); return
    sync_runtime_scripts()
    components = [
        ("topology-bootstrap", "/usr/local/lib/lfcs/topology.sh reset", None),
        ("extended", "/usr/local/lib/lfcs/extended-engine.py reset-all all", None),
        ("topology", "/usr/local/lib/lfcs/topology.sh reset", None),
        ("storage", "/usr/local/lib/lfcs/storage.sh reset-all", None),
        ("final-health", "bash -s", (ROOT / "tests/reset-health.sh").read_text(encoding="utf-8")),
    ]
    for name, command, payload in components:
        result = guest(command, input=payload, capture=True, check=False)
        if result.returncode:
            print(f"RESET-ALL FAILED: {name} (exit {result.returncode})", file=sys.stderr)
            if result.stdout.strip(): print(result.stdout.rstrip(), file=sys.stderr)
            if result.stderr.strip(): print(result.stderr.rstrip(), file=sys.stderr)
            raise SystemExit(result.returncode or 1)
        print(f"RESET-ALL PASS: {name}")
    ensure_student_admin()
    ensure_host_access()
    special = instance_info(SPECIAL_INSTANCE)
    if special:
        require_owned(SPECIAL_INSTANCE)
        if special.get("status") != "Running": lima("start", "--mount-none", "--tty=false", SPECIAL_INSTANCE)
        sync_special_runtime_scripts()
        result = guest("/usr/local/lib/lfcs/special-engine.py reset-all all", instance=SPECIAL_INSTANCE,
                       capture=True, check=False)
        if result.returncode:
            print("RESET-ALL FAILED: special", file=sys.stderr)
            raise SystemExit(result.returncode)
        print("RESET-ALL PASS: special")
    print("All lab-owned runtime state restored; the VM, packages, preserved Podman resources, and progress remain.")

def cmd_hosts(args):
    print(f"{'HOST':<14} {'ROLE':<34} STATUS")
    for name, role in ((INSTANCE, "Ubuntu primary practice host"),
                       (SPECIAL_INSTANCE, "Fedora SELinux/LDAP host")):
        info = instance_info(name)
        print(f"{name:<14} {role:<34} {info.get('status') if info else 'Not created'}")
    for name in sorted(NAMESPACES):
        print(f"{name:<14} {'Ubuntu network namespace':<34} inside {INSTANCE}")

def cmd_complete(args):
    kind = args[0] if args else "commands"
    if kind == "commands": print(" ".join(sorted((set(COMMANDS) - {"_complete"}) | {"help"})))
    elif kind == "scenarios": print(" ".join(x["id"] for x in LABS))
    elif kind == "hosts": print(" ".join([INSTANCE, SPECIAL_INSTANCE, *sorted(NAMESPACES)]))
    elif kind == "minis": print(" ".join(sorted(MINIS)))
    elif kind == "mocks": print(" ".join(sorted(MOCKS)))
    else: raise SystemExit(2)

def cmd_rebuild(args):
    print("Emergency maintenance only: this recreates the named lfcs VM but retains project files and progress.")
    if "--yes" not in args and input("Type REBUILD-LFCS to continue: ").strip()!="REBUILD-LFCS": print("Cancelled."); return
    cmd_destroy(["--yes"]); cmd_start([])

def cmd_container_clean(args):
    require_running(); guest("docker rm -f web-basil web-mint web-fern web-ivy 2>/dev/null || true; docker image prune -f >/dev/null")
    print("Removed only LFCS-owned Docker containers and dangling Docker layers; preserved Podman resources remain.")

def cmd_cleanup(args):
    require_running(); guest("docker rm -f web-basil web-mint web-fern web-ivy 2>/dev/null || true; docker image prune -f >/dev/null; apt-get clean; rm -rf /var/lib/apt/lists/* /var/log/lfcs-lab/*; journalctl --vacuum-size=24M >/dev/null 2>&1 || true; /usr/local/lib/lfcs/storage.sh reset-all")
    print("Cleaned only lab-owned caches, logs, containers, and sparse practice disks."); cmd_disk_usage([])

def cmd_destroy(args):
    info=instance_info()
    if not info: print("LFCS VM does not exist."); return
    require_owned(INSTANCE)
    print(f"This will permanently delete only Lima instance {INSTANCE!r} and its VM disk.")
    print("It will NOT delete the unrelated 'default' instance, Lima caches, or this project.")
    if "--yes" not in args and input("Type DELETE-LFCS to continue: ").strip() != "DELETE-LFCS": print("Cancelled."); return
    if info.get("status")=="Running": lima("stop",INSTANCE)
    lima("delete",INSTANCE)
    forget_owned(INSTANCE)
    print(f"Deleted Lima instance {INSTANCE!r}. The project and progress file remain.")

def cmd_uninstall(args):
    present = [name for name in (INSTANCE, SPECIAL_INSTANCE) if instance_info(name)]
    for name in present: require_owned(name)
    if not present:
        print("No simulator-owned VMs found. Learner files were retained.")
        return
    print("This deletes simulator-owned VMs and their virtual disks: " + ", ".join(present))
    print("Project files, learner progress, Lima itself, and unrelated VMs are retained.")
    if "--yes" not in args and input("Type UNINSTALL-LFCS to continue: ").strip() != "UNINSTALL-LFCS":
        print("Cancelled.")
        return
    for name in present:
        if instance_info(name).get("status") == "Running": lima("stop", name)
        lima("delete", name)
        forget_owned(name)
        print(f"Deleted owned VM {name}.")

COMMANDS={"doctor":cmd_doctor,"setup":cmd_setup,"start":cmd_start,"stop":cmd_stop,"status":cmd_status,"hosts":cmd_hosts,"disk-usage":cmd_disk_usage,"list":cmd_list,"day":cmd_day,"lab":cmd_lab,"reset":cmd_reset,"reset-all":cmd_reset_all,"rebuild":cmd_rebuild,"hint":cmd_hint,"solution":cmd_solution,"grade":cmd_grade,"shell":cmd_shell,"mini":cmd_mini,"mini-reset":cmd_mini,"mini-grade":cmd_mini_grade,"mock":cmd_mock,"mock-reset":cmd_mock,"mock-grade":cmd_mock_grade,"progress":cmd_progress,"weaknesses":cmd_weaknesses,"mistakes":cmd_mistakes,"cleanup":cmd_cleanup,"container-clean":cmd_container_clean,"destroy":cmd_destroy,"uninstall":cmd_uninstall,"_complete":cmd_complete}

def usage():
    command = r".\lfcs.ps1" if os.name == "nt" else "./bin/lfcs"
    print(f"Linux Admin Practice Lab\n\nUsage: {command} COMMAND [ARGS]\n\nCommands:\n  doctor | setup           Check host prerequisites without installing packages\n  start [lfcs-special]     Start the primary host, or explicitly start the special host\n  stop [lfcs-special]      Stop the primary host, or explicitly stop the special host\n  status | hosts           Inspect host state and routing targets\n  list [DAY|DOMAIN|special]\n  day N | lab ID | shell [HOST]\n  grade ID | hint ID | solution ID | reset ID | reset-all\n  mini N | mini-grade N (1..5)\n  mock N | mock-grade N | mock-reset N (1..6)\n  progress | weaknesses | mistakes\n  disk-usage | cleanup | container-clean | rebuild | destroy | uninstall\n\nSpecial-host scenarios auto-create/start lfcs-special. Ordinary commands retain the Ubuntu-only startup path.\nCompletion setup: eval \"$(./bin/completion-setup zsh)\" (or bash).")

if __name__=="__main__":
    if len(sys.argv)<2 or sys.argv[1] in ("-h","--help","help"): usage()
    elif sys.argv[1] not in COMMANDS: usage(); raise SystemExit(2)
    else: COMMANDS[sys.argv[1]](sys.argv[2:])
