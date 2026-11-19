#!/usr/bin/env python3
"""Refuse privileged helpers outside a candidate-owned Linux guest.

The host injects a fresh key into this root-only verifier when it starts each VM.
The marker is bound to that guest's machine ID and Lima instance name.
"""
import hashlib
import hmac
import os
import pathlib
import re
import stat
import sys

MARKER = pathlib.Path('/etc/lfcs-release-candidate/identity')
DIRECTORY = MARKER.parent
KEY = '__LFCS_GUEST_KEY__'

def valid():
    if os.name != 'posix' or not pathlib.Path('/proc/sys/kernel').is_dir():
        return False
    if os.geteuid() != 0 or not re.fullmatch(r'[0-9a-f]{64}', KEY):
        return False
    for path, mode, directory in ((DIRECTORY, 0o700, True), (MARKER, 0o600, False)):
        info = path.lstat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != mode:
            return False
        if directory and not stat.S_ISDIR(info.st_mode):
            return False
        if not directory and not stat.S_ISREG(info.st_mode):
            return False
    contents = MARKER.read_text().strip().split(':')
    if len(contents) != 4 or contents[0] != 'lfcs-release-candidate-v2':
        return False
    _, instance, machine_id, digest = contents
    if instance not in {'lfcs-rc-ubuntu', 'lfcs-rc-fedora'}:
        return False
    if not re.fullmatch(r'[0-9a-f]{32}', machine_id) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        return False
    if machine_id != pathlib.Path('/etc/machine-id').read_text().strip():
        return False
    message = ':'.join(contents[:3]).encode()
    expected = hmac.new(bytes.fromhex(KEY), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)

try:
    if valid():
        raise SystemExit(0)
except (OSError, UnicodeError, ValueError):
    pass
print('LFCS: candidate guest marker missing or invalid', file=sys.stderr)
raise SystemExit(1)
