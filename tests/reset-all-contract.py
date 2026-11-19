#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
spec = importlib.util.spec_from_file_location("lfcs_cli", ROOT / "lib/lfcs.py")
lfcs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lfcs)

COMPONENTS = {
    "extended": "/usr/local/lib/lfcs/extended-engine.py reset-all all",
    "topology": "/usr/local/lib/lfcs/topology.sh reset",
    "storage": "/usr/local/lib/lfcs/storage.sh reset-all",
    "final-health": "bash -s",
}

class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

def exercise(failing):
    calls = []
    def fake_guest(command, **kwargs):
        calls.append(command)
        if command == COMPONENTS[failing]:
            return Result(42, "forced stdout", "forced stderr")
        return Result(0, "TOTAL=40 PASS=40 FAIL=0\n" if command == "bash -s" else "")
    old = lfcs.guest, lfcs.require_running, lfcs.ensure_student_admin, lfcs.ensure_host_access
    lfcs.guest = fake_guest
    lfcs.require_running = lambda: None
    lfcs.ensure_student_admin = lambda: None
    lfcs.ensure_host_access = lambda: None
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                lfcs.cmd_reset_all(["--yes"])
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError(f"{failing} failure was masked")
    finally:
        lfcs.guest, lfcs.require_running, lfcs.ensure_student_admin, lfcs.ensure_host_access = old
    rendered = output.getvalue()
    assert f"RESET-ALL FAILED: {failing}" in rendered
    assert "All lab-owned runtime state restored" not in rendered
    return rendered, calls

for component in COMPONENTS:
    rendered, calls = exercise(component)
    print(f"PASS\t{component} failure propagated and success was suppressed")

print("TOTAL=4 PASS=4 FAIL=0")
