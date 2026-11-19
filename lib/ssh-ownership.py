#!/usr/bin/env python3
"""Capture and restore the shared SSH state owned by LFCS scenarios.

The exam key is infrastructure-owned and has one canonical, restrictive
baseline. Scenario snapshots cover only exact files and directory metadata;
unrelated SSH client files and the system SSH configuration are never swept.
"""

import json
import os
import pathlib
import pwd
import shutil
import subprocess
import sys

if not pathlib.Path('/usr/local/lib/lfcs/verify-guest.py').is_file() or subprocess.run(['/usr/local/lib/lfcs/verify-guest.py'], capture_output=True).returncode:
    raise SystemExit('LFCS SSH helper: candidate guest marker missing')


STATE = pathlib.Path("/var/lib/lfcs-lab/ssh-ownership")
FIXTURE = pathlib.Path("/var/lib/lfcs-lab/ssh-fixture")
KEY_DIR = pathlib.Path("/srv/lfcs/keys")
STUDENT_SSH = pathlib.Path("/home/student/.ssh")

SCENARIOS = (
    "networking-08", "networking-09", "advanced-10", "sshfs-01",
    "ssh-match-01", "ssh-match-02", "ssh-match-03",
)

COMMON_KEY_PATHS = (
    KEY_DIR,
    KEY_DIR / "exam",
    KEY_DIR / "exam.pub",
    STUDENT_SSH,
    STUDENT_SSH / "authorized_keys",
)

OWNED_PATHS = {
    "networking-08": COMMON_KEY_PATHS + (pathlib.Path("/etc/lfcs-lab/sshd-node2.conf"),),
    "networking-09": COMMON_KEY_PATHS + (pathlib.Path("/etc/lfcs-lab/sshd-node3.conf"),),
    "advanced-10": COMMON_KEY_PATHS + (pathlib.Path("/etc/lfcs-lab/sshd-node2.conf"),),
    "sshfs-01": COMMON_KEY_PATHS + (pathlib.Path("/etc/lfcs-lab/sshd-node2.conf"),),
    "ssh-match-01": (pathlib.Path("/etc/lfcs-lab/sshd-match.conf"),),
    "ssh-match-02": (pathlib.Path("/etc/lfcs-lab/sshd-match.conf"),),
    "ssh-match-03": (
        pathlib.Path("/etc/lfcs-lab/sshd-match.conf"),
        pathlib.Path("/tmp/deployer-banner"),
    ),
}

RUNTIME_PATHS = {
    "networking-08": ("sshd-node2",),
    "networking-09": ("sshd-node3",),
    "advanced-10": ("sshd-node2",),
    "sshfs-01": ("sshd-node2",),
}


def run(*args, input_text=None):
    return subprocess.run(args, text=True, input=input_text,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          check=False)


def lexists(path):
    return os.path.lexists(path)


def remove_file(path):
    path = pathlib.Path(path)
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)


def student_ids():
    user = pwd.getpwnam("student")
    return user.pw_uid, user.pw_gid


def public_material(path):
    try:
        fields = pathlib.Path(path).read_text().split()
        return " ".join(fields[:2]) if len(fields) >= 2 else ""
    except OSError:
        return ""


def fixture_valid():
    private = FIXTURE / "exam"
    public = FIXTURE / "exam.pub"
    if not private.is_file() or not public.is_file():
        return False
    derived = run("ssh-keygen", "-y", "-f", str(private)).stdout.strip()
    return bool(derived) and public_material(public) == public_material_text(derived)


def public_material_text(text):
    fields = text.split()
    return " ".join(fields[:2]) if len(fields) >= 2 else ""


def install_fresh(source, target, uid, gid, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".lfcs-new")
    temporary.unlink(missing_ok=True)
    shutil.copyfile(source, temporary)
    os.chown(temporary, uid, gid)
    os.chmod(temporary, mode)
    os.replace(temporary, target)


def ensure_baseline():
    FIXTURE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chown(FIXTURE, 0, 0)
    os.chmod(FIXTURE, 0o700)
    if not fixture_valid():
        shutil.rmtree(FIXTURE)
        FIXTURE.mkdir(parents=True, mode=0o700)
        result = run("ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                     "-C", "lfcs-exam", "-f", str(FIXTURE / "exam"))
        if result.returncode:
            raise SystemExit("failed to create canonical LFCS SSH key fixture")
    os.chown(FIXTURE / "exam", 0, 0)
    os.chown(FIXTURE / "exam.pub", 0, 0)
    os.chmod(FIXTURE / "exam", 0o600)
    os.chmod(FIXTURE / "exam.pub", 0o644)

    uid, gid = student_ids()
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    os.chown(KEY_DIR, uid, gid)
    os.chmod(KEY_DIR, 0o755)
    install_fresh(FIXTURE / "exam", KEY_DIR / "exam", uid, gid, 0o600)
    install_fresh(FIXTURE / "exam.pub", KEY_DIR / "exam.pub", uid, gid, 0o644)


def snapshot_dir(sid):
    return STATE / sid


def local_group_lines(name):
    result = {"group": None, "gshadow": None}
    for kind, raw in (("group", "/etc/group"), ("gshadow", "/etc/gshadow")):
        path = pathlib.Path(raw)
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            if line.split(":", 1)[0] == name:
                result[kind] = line
                break
    return result


def replace_account_line(path, name, baseline):
    source = pathlib.Path(path)
    lines = source.read_text().splitlines() if source.is_file() else []
    lines = [line for line in lines if line.split(":", 1)[0] != name]
    if baseline is not None:
        lines.append(baseline)
    source.write_text("\n".join(lines) + "\n")


def restore_remoteops(baseline):
    replace_account_line("/etc/group", "remoteops", baseline.get("group"))
    if pathlib.Path("/etc/gshadow").exists():
        replace_account_line("/etc/gshadow", "remoteops", baseline.get("gshadow"))


def capture(sid):
    if sid not in OWNED_PATHS:
        raise SystemExit(f"unknown SSH-owning scenario: {sid}")
    target = snapshot_dir(sid)
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, mode=0o700)
    paths = [path for path in OWNED_PATHS[sid] if lexists(path)]
    manifest = {
        "scenario": sid,
        "existing": [str(path) for path in paths],
    }
    if sid == "networking-09":
        manifest["remoteops"] = local_group_lines("remoteops")
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if paths:
        relative = [str(path).lstrip("/") for path in paths]
        result = run("tar", "--acls", "--xattrs", "--numeric-owner", "-cpf",
                     str(target / "baseline.tar"), "--no-recursion", "-C", "/", *relative)
        if result.returncode:
            raise SystemExit(f"failed to capture SSH baseline for {sid}")


def stop_runtime(sid):
    for name in RUNTIME_PATHS.get(sid, ()):
        pid_file = pathlib.Path(f"/run/lfcs-lab/{name}.pid")
        try:
            pid = int(pid_file.read_text().strip())
        except (OSError, ValueError):
            pid = None
        if pid:
            run("kill", str(pid))
        pid_file.unlink(missing_ok=True)
        pathlib.Path(f"/run/lfcs-lab/{name}.log").unlink(missing_ok=True)


def remove_exam_authorization():
    authorized = STUDENT_SSH / "authorized_keys"
    exam = public_material(FIXTURE / "exam.pub")
    if not authorized.is_file() or not exam:
        return
    lines = authorized.read_text().splitlines()
    kept = [line for line in lines if public_material_text(line) != exam]
    if kept:
        authorized.write_text("\n".join(kept) + "\n")
    else:
        authorized.unlink()


def reset(sid):
    if sid not in OWNED_PATHS:
        raise SystemExit(f"unknown SSH-owning scenario: {sid}")
    stop_runtime(sid)
    target = snapshot_dir(sid)
    manifest_path = target / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        existing = set(manifest.get("existing", ()))
        for path in OWNED_PATHS[sid]:
            if str(path) not in existing:
                remove_file(path)
        archive = target / "baseline.tar"
        if archive.is_file():
            result = run("tar", "--acls", "--xattrs", "--numeric-owner", "-xpf",
                         str(archive), "-C", "/")
            if result.returncode:
                raise SystemExit(f"failed to restore SSH baseline for {sid}")
        if sid == "networking-09":
            restore_remoteops(manifest.get("remoteops", {}))
        shutil.rmtree(target, ignore_errors=True)
    else:
        # Migration from the old reset model: remove only reserved configs and
        # the exact generated exam-key authorization, preserving all other SSH
        # client and authorized_keys content.
        for path in OWNED_PATHS[sid]:
            if path not in COMMON_KEY_PATHS:
                remove_file(path)
        if sid in {"networking-08", "networking-09", "advanced-10", "sshfs-01"}:
            ensure_baseline()
            remove_exam_authorization()
        if sid == "networking-09":
            restore_remoteops({})
    if sid in {"networking-08", "networking-09", "advanced-10", "sshfs-01"}:
        ensure_baseline()


def reset_all():
    if STATE.is_dir():
        snapshots = sorted(
            (path for path in STATE.iterdir() if path.name in SCENARIOS),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in snapshots:
            reset(path.name)
    for sid in SCENARIOS:
        stop_runtime(sid)
    for raw in (
        "/etc/lfcs-lab/sshd-node2.conf",
        "/etc/lfcs-lab/sshd-node3.conf",
        "/etc/lfcs-lab/sshd-match.conf",
        "/tmp/deployer-banner",
    ):
        remove_file(raw)
    ensure_baseline()
    remove_exam_authorization()
    restore_remoteops({})
    shutil.rmtree(STATE, ignore_errors=True)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"ensure-baseline", "capture", "reset", "reset-all", "abandon"}:
        raise SystemExit("usage: ssh-ownership.py ensure-baseline | capture|reset|abandon SCENARIO | reset-all")
    command = sys.argv[1]
    if command == "ensure-baseline":
        ensure_baseline()
    elif command == "reset-all":
        reset_all()
    else:
        if len(sys.argv) != 3 or sys.argv[2] not in SCENARIOS:
            raise SystemExit("a known SSH-owning scenario id is required")
        if command == "capture":
            capture(sys.argv[2])
        elif command == "reset":
            reset(sys.argv[2])
        else:
            shutil.rmtree(snapshot_dir(sys.argv[2]), ignore_errors=True)


if __name__ == "__main__":
    main()
