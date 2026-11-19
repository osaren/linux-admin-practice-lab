#!/usr/bin/env python3
"""Capture and restore nginx state owned by LFCS scenarios.

Each nginx exercise gets a pre-stage snapshot of the existing nginx config and
service state.  Reset restores that snapshot, removes only names/signatures
owned by the exercise, and leaves unrelated files created after staging alone.
The signature pass is intentionally narrow: it migrates answers created with
older workbook filenames such as proxy.conf and server.conf without treating
every nginx file as lab-owned.
"""

import hashlib
import json
import os
import pathlib
import re
import signal
import shutil
import subprocess
import sys
import tarfile
import time

if not pathlib.Path('/usr/local/lib/lfcs/verify-guest.py').is_file() or subprocess.run(['/usr/local/lib/lfcs/verify-guest.py'], capture_output=True).returncode:
    raise SystemExit('LFCS nginx helper: candidate guest marker missing')


STATE = pathlib.Path("/var/lib/lfcs-lab/nginx-ownership")
CONFIG_ROOTS = (
    pathlib.Path("/etc/nginx/sites-available"),
    pathlib.Path("/etc/nginx/sites-enabled"),
    pathlib.Path("/etc/nginx/conf.d"),
)
SCENARIOS = (
    "operations-08",
    "nginx-01", "nginx-02", "nginx-03", "nginx-04", "nginx-05", "nginx-06",
    "advanced-07", "advanced-08", "storage-12",
)
PORTS = {
    "operations-08": (8091,),
    "nginx-01": (8111,),
    "nginx-02": (8112,),
    "nginx-03": (8113,),
    "nginx-04": (8114,),
    "nginx-05": (8115, 8116),
    "nginx-06": (8446,),
    "advanced-07": (8088,),
    "advanced-08": (8089,),
    "storage-12": (8443,),
}

# Reserved names are unambiguously LFCS-owned.  Legacy names are removed on an
# initial migration only when their content has the scenario's unique marker.
OWNERSHIP = {
    "operations-08": {
        "reserved": ("day1",),
        "legacy": ("server.conf", "day1.conf"),
        "extra": (),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8091(?:\s|;)", r"day1-ready"),
        "baseline_paths": ("/etc/nginx/sites-available/default",
                           "/etc/nginx/sites-enabled/default"),
    },
    "nginx-01": {
        "reserved": ("lfcs-ext-amber", "lfcs-ext-amber.conf"),
        "legacy": ("lfcs-listener.conf", "listener.conf", "amber.conf",
                   "lfcs-amber", "lfcs-amber.conf"),
        "extra": (),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8111(?:\s|;)", r"amber-ready"),
    },
    "nginx-02": {
        "reserved": ("lfcs-ext-alder", "lfcs-ext-alder.conf"),
        "legacy": ("alder.conf",),
        "extra": ("/srv/lfcs/alder",),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8112(?:\s|;)",
                     r"/srv/lfcs/(?:alder|missing)"),
    },
    "nginx-03": {
        "reserved": ("lfcs-ext-proxy", "lfcs-ext-proxy.conf"),
        "legacy": ("proxy.conf",),
        "extra": (),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8113(?:\s|;)", r"\bproxy_pass\b"),
    },
    "nginx-04": {
        "reserved": ("lfcs-ext-api", "lfcs-ext-api.conf"),
        "legacy": ("api.conf",),
        "extra": (),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8114(?:\s|;)", r"\bproxy_pass\b"),
    },
    "nginx-05": {
        "reserved": ("lfcs-ext-twin", "lfcs-ext-twin.conf"),
        "legacy": ("twin.conf",),
        "extra": (),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8115(?:\s|;)",
                     r"\blisten\s+(?:[^;\n]*:)?8116(?:\s|;)"),
    },
    "nginx-06": {
        "reserved": ("lfcs-ext-fern", "lfcs-ext-fern.conf"),
        "legacy": ("fern.conf",),
        "extra": ("/etc/lfcs/tls/fern",),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8446(?:\s|;)",
                     r"(?:fern-secure|/etc/lfcs/tls/fern/)"),
    },
    "advanced-07": {
        "reserved": ("lfcs-proxy", "lfcs-proxy.conf"),
        "legacy": ("reverse-proxy.conf",),
        "extra": (),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8088(?:\s|;)", r"\bproxy_pass\b"),
    },
    "advanced-08": {
        "reserved": ("lfcs-lb", "lfcs-lb.conf"),
        "legacy": ("lb.conf", "upstream.conf"),
        "extra": (),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8089(?:\s|;)", r"lfcs_backends"),
    },
    "storage-12": {
        "reserved": ("lfcs-tls", "lfcs-tls.conf"),
        "legacy": ("tls.conf",),
        "extra": ("/etc/lfcs/tls/server.key", "/etc/lfcs/tls/server.crt"),
        "patterns": (r"\blisten\s+(?:[^;\n]*:)?8443(?:\s|;)",
                     r"(?:secure-ready|/etc/lfcs/tls/(?:server|missing))"),
    },
}


def run(*args):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, check=False)


def service_state():
    active = run("systemctl", "is-active", "nginx").stdout.strip() or "inactive"
    enabled = run("systemctl", "is-enabled", "nginx").stdout.strip() or "disabled"
    return {"active": active, "enabled": enabled}


def lexists(path):
    return os.path.lexists(path)


def remove(path):
    path = pathlib.Path(path)
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def baseline_entries():
    entries = []
    main = pathlib.Path("/etc/nginx/nginx.conf")
    if lexists(main):
        entries.append(main)
    for root in CONFIG_ROOTS:
        if root.is_dir():
            entries.extend(sorted(root.iterdir(), key=lambda p: p.name))
    return entries


def snapshot_dir(sid):
    return STATE / sid


def capture(sid):
    if sid not in OWNERSHIP:
        return
    target = snapshot_dir(sid)
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, mode=0o700)
    entries = baseline_entries()
    for raw in OWNERSHIP[sid]["extra"]:
        path = pathlib.Path(raw)
        if lexists(path) and path not in entries:
            entries.append(path)
    manifest = {
        "scenario": sid,
        "service": service_state(),
        "entries": [str(path) for path in entries],
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with tarfile.open(target / "baseline.tar", "w") as archive:
        for path in entries:
            archive.add(path, arcname=str(path).lstrip("/"), recursive=True)


def candidate_paths(sid, *, include_legacy=True):
    spec = OWNERSHIP[sid]
    names = list(spec["reserved"])
    if include_legacy:
        names.extend(spec["legacy"])
    for root in CONFIG_ROOTS:
        for name in names:
            yield root / name


def content_matches(path, sid):
    try:
        resolved = path.resolve(strict=True) if path.is_symlink() else path
        if not resolved.is_file():
            return False
        text = resolved.read_text(errors="replace")
    except (OSError, RuntimeError):
        return False
    return all(re.search(pattern, text, re.MULTILINE) for pattern in OWNERSHIP[sid]["patterns"])


def cleanup_owned(sid, baseline, *, migration=False):
    spec = OWNERSHIP[sid]
    removed_artifact = False
    removed_paths = set()

    # Reserved LFCS names are always owned unless they existed at stage time.
    for path in candidate_paths(sid, include_legacy=False):
        if str(path) not in baseline and lexists(path):
            remove(path)
            removed_paths.add(str(path))
            removed_artifact = True

    # Generic historical names require a matching lab signature when there is
    # no stage snapshot; with a snapshot, a newly-created candidate is owned.
    for root in CONFIG_ROOTS:
        for name in spec["legacy"]:
            path = root / name
            if str(path) in baseline or not lexists(path):
                continue
            if not migration or content_matches(path, sid):
                remove(path)
                removed_paths.add(str(path))
                removed_artifact = True

    # Catch a learner's alternative filename by its pair of scenario-unique
    # directives.  Never remove a file/symlink that was present at stage time.
    for root in CONFIG_ROOTS:
        if not root.is_dir():
            continue
        for path in list(root.iterdir()):
            if str(path) in baseline or not lexists(path):
                continue
            if content_matches(path, sid):
                remove(path)
                removed_paths.add(str(path))
                removed_artifact = True

    # Remove enabled links whose target was just removed.  Unrelated dangling
    # links are deliberately preserved rather than "repaired" or swept up.
    enabled = pathlib.Path("/etc/nginx/sites-enabled")
    if enabled.is_dir():
        for link in list(enabled.iterdir()):
            if str(link) in baseline or not link.is_symlink():
                continue
            try:
                target = link.resolve(strict=True)
            except (FileNotFoundError, RuntimeError):
                # A historical answer can use one scenario's generic filename
                # while its content belongs to another scenario (for example
                # proxy.conf containing the advanced-07 port).  If this pass
                # removed that target, remove the newly dangling link too.
                target = str(link.resolve(strict=False))
                if (link.name in set(spec["reserved"]) | set(spec["legacy"])
                        or target in removed_paths):
                    link.unlink(missing_ok=True)
                    removed_paths.add(str(link))
                    removed_artifact = True
                continue
            if content_matches(target, sid):
                link.unlink(missing_ok=True)
                removed_paths.add(str(link))
                removed_artifact = True

    if removed_artifact or not migration:
        for extra in spec["extra"]:
            if extra not in baseline and lexists(extra):
                remove(extra)
    return removed_artifact


def restore_archive(target, manifest):
    entries = set(manifest.get("entries", ()))
    for path in sorted(entries, key=lambda value: value.count("/"), reverse=True):
        if lexists(path):
            remove(path)
    archive_path = target / "baseline.tar"
    if archive_path.is_file():
        with tarfile.open(archive_path) as archive:
            try:
                archive.extractall("/", filter="fully_trusted")
            except TypeError:  # Python before the extraction-filter API.
                archive.extractall("/")


def restore_service(state):
    enabled = state.get("enabled", "disabled")
    active = state.get("active", "inactive")
    if enabled == "enabled":
        run("systemctl", "enable", "nginx")
    elif enabled in {"disabled", "indirect", "not-found"}:
        run("systemctl", "disable", "nginx")
    if active == "active":
        if run("nginx", "-t").returncode == 0:
            run("systemctl", "start", "nginx")
            run("systemctl", "reload", "nginx")
    else:
        run("systemctl", "stop", "nginx")
    run("systemctl", "reset-failed", "nginx")


def stop_owned_listeners(ports):
    """Stop nginx processes actually owning LFCS-reserved listener ports."""
    ports = tuple(ports)
    output = run("ss", "-H", "-ltnp").stdout
    pids = set()
    for line in output.splitlines():
        if not any(re.search(rf":{port}(?:\s|$)", line) for port in ports):
            continue
        pids.update(int(raw) for raw in re.findall(r"pid=(\d+)", line))
    nginx_pids = []
    for pid in pids:
        try:
            if pathlib.Path(f"/proc/{pid}/comm").read_text().strip() == "nginx":
                nginx_pids.append(pid)
        except OSError:
            pass
    for pid in nginx_pids:
        try:
            os.kill(pid, signal.SIGQUIT)
        except ProcessLookupError:
            pass
    for _ in range(50):
        if not any(pathlib.Path(f"/proc/{pid}").exists() for pid in nginx_pids):
            break
        time.sleep(0.02)
    for pid in nginx_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def reset(sid):
    if sid not in OWNERSHIP:
        return
    target = snapshot_dir(sid)
    manifest_path = target / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        run("systemctl", "stop", "nginx")
        stop_owned_listeners(PORTS[sid])
        baseline = set(manifest.get("entries", ()))
        cleanup_owned(sid, baseline)
        restore_archive(target, manifest)
        restore_service(manifest.get("service", {}))
        shutil.rmtree(target, ignore_errors=True)
    else:
        removed = cleanup_owned(sid, set(), migration=True)
        if removed:
            restore_service({"active": "inactive", "enabled": "disabled"})


def package_default_is_pristine():
    default = pathlib.Path("/etc/nginx/sites-available/default")
    if not default.is_file():
        return False
    result = run("dpkg-query", "-W", "-f=${Conffiles}", "nginx-common")
    match = re.search(r"^\s*/etc/nginx/sites-available/default\s+([0-9a-f]{32})\s*$",
                      result.stdout, re.MULTILINE)
    if not match:
        return False
    return hashlib.md5(default.read_bytes()).hexdigest() == match.group(1)


def ensure_package_default_link():
    available = pathlib.Path("/etc/nginx/sites-available/default")
    enabled = pathlib.Path("/etc/nginx/sites-enabled/default")
    if not lexists(enabled) and package_default_is_pristine():
        enabled.parent.mkdir(parents=True, exist_ok=True)
        enabled.symlink_to(available)


def reset_all():
    # Ignore possibly nested scenario snapshots here: reset-all means the
    # provisioned lab baseline, not whichever other exercise was active when a
    # later scenario was staged.  Cleanup is still restricted to known LFCS
    # names and scenario-unique content signatures.
    run("systemctl", "stop", "nginx")
    stop_owned_listeners(port for values in PORTS.values() for port in values)
    for sid in SCENARIOS:
        cleanup_owned(sid, set(), migration=True)
    shutil.rmtree(STATE, ignore_errors=True)
    ensure_package_default_link()
    restore_service({"active": "inactive", "enabled": "disabled"})


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"capture", "reset", "reset-all"}:
        raise SystemExit("usage: nginx-ownership.py capture|reset SCENARIO | reset-all")
    command = sys.argv[1]
    if command == "reset-all":
        reset_all()
        return
    if len(sys.argv) != 3 or sys.argv[2] not in OWNERSHIP:
        raise SystemExit("a known nginx scenario id is required")
    if command == "capture":
        capture(sys.argv[2])
    else:
        reset(sys.argv[2])


if __name__ == "__main__":
    main()
