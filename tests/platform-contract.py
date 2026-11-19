#!/usr/bin/env python3
"""Exercise host selection, Windows script transfer and guarded dispatch offline."""
import pathlib
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import host_platform
import lfcs

for os_name, machine, expected in (
    ("Windows", "AMD64", ("windows", "amd64")),
    ("Windows", "ARM64", ("windows", "arm64")),
    ("Linux", "x86_64", ("linux", "amd64")),
    ("Linux", "aarch64", ("linux", "arm64")),
    ("Darwin", "x86_64", ("macos", "arm64")),
):
    with patch.object(host_platform.platform, "system", return_value=os_name), \
         patch.object(host_platform.platform, "machine", return_value=machine), \
         patch.dict(host_platform.os.environ, {"PROCESSOR_ARCHITEW6432": machine}), \
         patch.object(host_platform.pathlib.Path, "read_text", return_value="6.8.0"), \
         patch.object(host_platform.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "1\n")):
        assert host_platform.host_kind() == expected

for host, arch, suffix in (
    ("windows", "amd64", "-amd64-windows"),
    ("linux", "amd64", "-amd64-linux"),
    ("linux", "arm64", "-arm64-linux"),
    ("macos", "amd64", "-amd64-macos"),
    ("macos", "arm64", ""),
    ("wsl2", "amd64", "-amd64-wsl2"),
):
    with patch.object(lfcs, "host_kind", return_value=(host, arch)):
        assert lfcs.vm_config(lfcs.INSTANCE).name == f"lfcs{suffix}.yaml"
        assert lfcs.vm_config(lfcs.SPECIAL_INSTANCE).name == f"lfcs-special{suffix}.yaml"
with patch.object(lfcs, "host_kind", return_value=("windows", "arm64")):
    try:
        lfcs.vm_config(lfcs.INSTANCE)
    except SystemExit:
        pass
    else:
        raise AssertionError("Windows Arm selected a VM configuration")

assert host_platform.version_from("limactl version 2.3.0") == (2, 3, 0)
assert host_platform.version_from("limactl version 2.3.0-beta.1") is None
assert host_platform.version_from("QEMU emulator version 11.0.0 (v11.0.0)") == (11, 0, 0)

with patch.object(lfcs, "host_kind", return_value=("windows", "amd64")), \
     patch.object(lfcs, "lima") as lima, patch.object(lfcs, "record_owned") as owned:
    lfcs.create_instance(lfcs.INSTANCE)
    args, kwargs = lima.call_args
    assert args == ("create", "--name", lfcs.INSTANCE, "--mount-none", "--tty=false", "-")
    assert kwargs["input"].startswith("minimumLimaVersion: 2.3.0\n")
    owned.assert_called_once_with(lfcs.INSTANCE)

with patch.object(lfcs.os, "name", "nt"), patch.object(lfcs.subprocess, "run") as process:
    process.return_value = subprocess.CompletedProcess([], 0, b"ok\r\n", b"")
    assert lfcs.run(["limactl", "shell"], input="#!/bin/bash\n", capture=True).stdout == "ok\r\n"
    assert process.call_args.kwargs["input"] == b"#!/bin/bash\n"
    assert process.call_args.kwargs["text"] is False

(ROOT / "tmp").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="platform path ") as temp:
    root = pathlib.Path(temp)
    home = root / ".lima"
    ssh_dir = root / "System32" / "OpenSSH"
    tools = {name: str(ssh_dir / f"{name}.exe") for name in ("ssh", "scp", "ssh-keygen")}
    tools.update({name: str(root / f"{name}.exe") for name in ("limactl", "qemu-system-x86_64", "qemu-img")})

    lima_version = "2.3.0"
    qemu_version = "11.0.0"

    def probe(args, **kwargs):
        output = ("whpx\n" if args[1:] == ["-accel", "help"] else
                  f"limactl version {lima_version}\n" if args[0] == tools["limactl"] else
                  f"QEMU emulator version {qemu_version}\n")
        return subprocess.CompletedProcess(args, 0, output, "")

    with patch.object(lfcs, "host_kind", return_value=("windows", "amd64")), \
         patch.object(lfcs.sys, "getwindowsversion", return_value=SimpleNamespace(build=22631), create=True), \
         patch.dict(lfcs.os.environ, {"SystemRoot": str(root)}), \
         patch.object(lfcs.shutil, "which", side_effect=tools.get), \
         patch.object(lfcs.shutil, "disk_usage", return_value=SimpleNamespace(free=20 * 1024**3)), \
         patch.object(lfcs, "host_memory", return_value=(8 * 1024**3, 4 * 1024**3)), \
         patch.object(lfcs, "windows_local_ntfs", return_value=True), \
         patch.object(lfcs, "windows_hypervisor", return_value=True) as hypervisor, \
         patch.object(lfcs, "instance_info", return_value=None), patch.object(lfcs, "run", side_effect=probe):
        with redirect_stdout(StringIO()) as output:
            assert lfcs.preflight()
            hypervisor.return_value = False
            assert not lfcs.preflight()
            hypervisor.return_value = True
            lima_version = "2.2.0"
            qemu_version = "10.2.0"
            assert not lfcs.preflight()
        assert "FAIL: Windows Hypervisor Platform" in output.getvalue()
        assert "FAIL: Lima version 2.2.0" in output.getvalue()
        assert "FAIL: qemu-system-x86_64 version 10.2.0" in output.getvalue()

    with patch.object(lfcs, "ROOT", root), patch.object(lfcs, "LIMA_HOME", home), patch.object(lfcs, "run") as run:
        assert lfcs.instance_info() is None
        run.assert_not_called()
        lfcs.lima("create", "--name", lfcs.INSTANCE)
        config = home / "_config" / "networks.yaml"
        assert config.read_text() == "networks: {}\n"
        run.reset_mock()
        config.write_text("networks: {shared: {mode: shared}}\n")
        try:
            lfcs.lima("start", lfcs.INSTANCE)
        except SystemExit as exc:
            assert "Refusing custom Lima networks" in str(exc)
        else:
            raise AssertionError("managed networking accepted")
        run.assert_not_called()

print("PASS: host and image selection, mocked WHPX preflight, Windows LF transfer, guarded Lima dispatch")
