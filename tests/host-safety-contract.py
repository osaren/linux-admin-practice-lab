#!/usr/bin/env python3
"""Offline guards against acting on a same-named, unowned VM."""
import importlib.util
import pathlib
import os
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
spec = importlib.util.spec_from_file_location("lfcs_safety", ROOT / "lib/lfcs.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

launcher = ([sys.executable, str(ROOT / "lib/lfcs.py")] if os.name == "nt"
            else [str(ROOT / "bin/lfcs")])
outside = subprocess.run([*launcher, "progress"],
                         cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "LFCS_PROGRESS_PATH": str(ROOT.parent / "lfcs-outside-progress.json")})
assert outside.returncode != 0 and "outside the candidate" in outside.stderr

(ROOT / "tmp").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
    cli.ROOT = pathlib.Path(directory)
    cli.STATE = cli.ROOT / "state"
    cli.STATE.mkdir()
    cli.OWNERSHIP = cli.STATE / "vm-ownership.json"
    calls = []
    cli.lima = lambda *args, **kw: calls.append(args)
    cli.instance_info = lambda name=cli.INSTANCE: {"name": name, "status": "Stopped"}
    try:
        cli.guest("true")
    except SystemExit as exc:
        assert "unowned" in str(exc)
    else:
        raise AssertionError("guest accepted an unowned VM")
    try:
        cli.cmd_uninstall(["--yes"])
    except SystemExit as exc:
        assert "unowned" in str(exc)
    else:
        raise AssertionError("uninstall accepted an unowned VM")
    assert not calls, "an unowned VM was mutated"
    cli.instance_info = lambda name=cli.INSTANCE: {"name": name, "status": "Running"}
    try:
        cli.cmd_status([])
    except SystemExit as exc:
        assert "unowned" in str(exc)
    else:
        raise AssertionError("status shell probe accepted an unowned VM")
    assert not calls, "status touched an unowned VM"
    cli.record_owned(cli.INSTANCE)
    assert cli.owned_names() == {cli.INSTANCE}
    cli.forget_owned(cli.INSTANCE)
    assert not cli.owned_names()
    print("PASS: unowned guest and uninstall blocked; external progress path refused; no Lima mutation")
