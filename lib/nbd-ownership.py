#!/usr/bin/env python3
"""Remove only NBD configuration owned by LFCS scenarios.

The learner may put an export in the package main file or in any file under
conf.d, and may choose any section name.  Ownership is therefore identified
by the exact lab backing image, not by one expected filename.  Unrelated
sections and files are retained byte-for-byte.
"""

from __future__ import annotations

import os
import json
import signal
import subprocess
import time
import pathlib
import re
import sys
import tempfile

if not pathlib.Path('/usr/local/lib/lfcs/verify-guest.py').is_file() or subprocess.run(['/usr/local/lib/lfcs/verify-guest.py'], capture_output=True).returncode:
    raise SystemExit('LFCS NBD helper: candidate guest marker missing')


ROOT = pathlib.Path("/etc/nbd-server")
MAIN = ROOT / "config"
INCLUDE = ROOT / "conf.d"
OWNED_BACKINGS = {
    "/var/lib/lfcs-disks/amber.img",
    "/var/lib/lfcs-disks/nbd.img",
}
SECTION = re.compile(r"^[ \t]*\[([^]\r\n]+)\][ \t]*(?:[#;].*)?$")
EXPORTNAME = re.compile(r"^[ \t]*exportname[ \t]*=[ \t]*(\S+)[ \t]*(?:[#;].*)?$", re.I)


def paths() -> list[pathlib.Path]:
    result = [MAIN]
    if INCLUDE.is_dir():
        result.extend(sorted(p for p in INCLUDE.iterdir() if p.is_file()))
    return result


def section_ranges(lines: list[str]) -> list[tuple[int, int, str]]:
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = SECTION.match(line.rstrip("\r\n"))
        if match:
            starts.append((index, match.group(1).strip()))
    return [
        (start, starts[pos + 1][0] if pos + 1 < len(starts) else len(lines), name)
        for pos, (start, name) in enumerate(starts)
    ]


def owned_range(lines: list[str], start: int, end: int, name: str, path: pathlib.Path) -> bool:
    if path.parent == INCLUDE and path.name == "amber.conf" and name == "amber":
        return True
    for line in lines[start + 1 : end]:
        match = EXPORTNAME.match(line.rstrip("\r\n"))
        if match and match.group(1).strip('"\'') in OWNED_BACKINGS:
            return True
    return False


def has_generic(lines: list[str]) -> bool:
    return any(name.lower() == "generic" for _, _, name in section_ranges(lines))


def canonical_generic() -> list[str]:
    return [
        "[generic]\n",
        "    allowlist = true\n",
        "    user = nbd\n",
        "    group = nbd\n",
        "    includedir = /etc/nbd-server/conf.d\n",
        "\n",
    ]


def write_preserving_metadata(path: pathlib.Path, lines: list[str]) -> None:
    stat = path.stat()
    xattrs: dict[str, bytes] = {}
    try:
        xattrs = {name: os.getxattr(path, name) for name in os.listxattr(path)}
    except OSError:
        pass
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".lfcs-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.writelines(lines)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.chmod(temporary, stat.st_mode & 0o7777)
        for name, value in xattrs.items():
            try:
                os.setxattr(temporary, name, value)
            except OSError as error:
                raise SystemExit(f"cannot preserve xattr {name!r} on {path}: {error}")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def clean_path(path: pathlib.Path) -> bool:
    try:
        original = path.read_text().splitlines(keepends=True)
    except (OSError, UnicodeError):
        return False
    remove: set[int] = set()
    for start, end, name in section_ranges(original):
        if owned_range(original, start, end, name, path):
            remove.update(range(start, end))
            if start and not original[start - 1].strip():
                remove.add(start - 1)
    rendered = [line for index, line in enumerate(original) if index not in remove]
    if path == MAIN and not has_generic(rendered):
        rendered = canonical_generic() + rendered
    if rendered == original:
        return False
    meaningful = [line for line in rendered if line.strip() and not line.lstrip().startswith(("#", ";"))]
    if path.parent == INCLUDE and not meaningful:
        path.unlink(missing_ok=True)
    else:
        write_preserving_metadata(path, rendered)
    return True


def find_owned() -> list[str]:
    found: list[str] = []
    for path in paths():
        try:
            lines = path.read_text().splitlines(keepends=True)
        except (OSError, UnicodeError):
            continue
        for start, end, name in section_ranges(lines):
            if owned_range(lines, start, end, name, path):
                found.append(f"{path}:[{name}]")
    return found


def teardown() -> None:
    """Detach only the NBD device mounted at a reserved LFCS target.

    A busy cwd can prevent the kernel releasing NBD. Refuse cleanup if the
    owned mount is busy, rather than signal a process by a reused PID.
    Ambiguous or unrelated device mounts are left alone.
    """
    def command(*args):
        return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    device = pathlib.Path("/dev/nbd0")
    mounts = json.loads(command("findmnt", "--json", "-S", str(device),
                                "-o", "SOURCE,TARGET").stdout or "{}").get("filesystems", [])
    owned_mounts = [m["target"] for m in mounts
                    if m["target"] in {"/mnt/lfcs/amber", "/mnt/lfcs/nbd"}]
    foreign = [m for m in mounts if m["target"] not in owned_mounts]
    if owned_mounts and foreign:
        raise SystemExit("LFCS NBD reset: device also mounted outside LFCS targets; preserved")
    exports = []
    for path in paths():
        try: lines = path.read_text().splitlines(keepends=True)
        except OSError: continue
        exports.extend((path, lines, start, end, name)
                       for start, end, name in section_ranges(lines)
                       if name.lower() != "generic")
    unrelated = any(not owned_range(lines, start, end, name, path)
                    for path, lines, start, end, name in exports)
    owned_device = bool(owned_mounts) and not foreign
    if owned_device and device.exists():
        for target in owned_mounts:
            result = command("timeout", "5", "umount", target)
            if result.returncode:
                raise SystemExit(f"LFCS NBD reset: cannot unmount {target}: {result.stderr}")
        result = command("timeout", "5", "nbd-client", "-d", str(device))
        for _ in range(100):
            if pathlib.Path("/sys/block/nbd0/size").read_text().strip() == "0": break
            time.sleep(.05)
        else: raise SystemExit("LFCS NBD reset: owned /dev/nbd0 remains attached")
    # A shared server must continue serving unrelated exports. Existing clients
    # retain their sessions; SIGHUP reloads the remaining configuration.
    had_owned = bool(find_owned())
    for path in paths(): clean_path(path)
    if had_owned and unrelated:
        command("systemctl", "kill", "--kill-who=main", "--signal=HUP", "nbd-server")
    elif had_owned:
        command("systemctl", "stop", "nbd-server")
        command("systemctl", "disable", "nbd-server")
    for backing in OWNED_BACKINGS:
        if command("fuser", backing).returncode != 0:
            pathlib.Path(backing).unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"clean", "check-clean", "teardown"}:
        raise SystemExit("usage: nbd-ownership.py clean|check-clean|teardown")
    if sys.argv[1] == "teardown":
        teardown()
    if sys.argv[1] == "clean":
        for path in paths():
            clean_path(path)
    residue = find_owned()
    if residue:
        print("LFCS-owned NBD exports remain: " + ", ".join(residue), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
