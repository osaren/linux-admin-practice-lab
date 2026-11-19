#!/usr/bin/env python3
"""Render local templates without creating instances or downloading guest images."""
import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from host_platform import host_kind

spec = importlib.util.spec_from_file_location("image_integrity", ROOT / "tests/image-integrity.py")
integrity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integrity)
RELEASE = "2.3.0"
ASSETS = {
    ("Darwin", "arm64"): ("Darwin-arm64.tar.gz", "b7af444bd8f91d3c307477e562f2cf3bd7595d62b9429185e4fa841563578cfc"),
    ("Darwin", "x86_64"): ("Darwin-x86_64.tar.gz", "d58bc7d6b8158d638720d8c8fdb17eb58527dfead6a29a5b60f48a35ee4a65a6"),
    ("Linux", "x86_64"): ("Linux-x86_64.tar.gz", "cc8ba97f1c801b899f7c9eda9919dfc4ce4fa2c140c53e5add15aa2d0a1936f9"),
    ("Windows", "amd64"): ("Windows-AMD64.zip", "fbd49036909ba3833ea8618743bd3a051eb21049c80c0772452f79ed45af99dc"),
}


def release_binary(scratch):
    suffix, expected = ASSETS[(platform.system(), platform.machine().lower())]
    asset = f"lima-{RELEASE}-{suffix}"
    url = f"https://github.com/lima-vm/lima/releases/download/v{RELEASE}/{asset}"
    archive = scratch / asset
    with urllib.request.urlopen(url, timeout=60) as stream:
        archive.write_bytes(stream.read(70 * 1024 * 1024))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit("Lima release archive SHA-256 mismatch")
    target = scratch / "lima-release"
    if asset.endswith(".zip"):
        shutil.unpack_archive(archive, target)
    else:
        shutil.unpack_archive(archive, target, filter="data")
    name = "limactl.exe" if platform.system() == "Windows" else "limactl"
    (binary,) = target.rglob(name)
    return str(binary)


def launcher_smoke(archive, scratch, lima, env):
    # CI supplies only the source ZIP just built and scanned by the preceding step.
    target = scratch / "review checkout with spaces"
    target.mkdir()
    with zipfile.ZipFile(archive) as release:
        for member in release.infolist():
            path = pathlib.PurePosixPath(member.filename)
            if (path.is_absolute() or len(path.parts) < 2 or path.parts[0] != "lfcs-prep-simulator"
                or ".." in path.parts or "\\" in member.filename or ":" in member.filename):
                raise SystemExit("Unexpected review ZIP entry")
            destination = target.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output:
                output.write(release.read(member))
            if os.name != "nt":
                destination.chmod((member.external_attr >> 16) & 0o777)
    checkout = target / "lfcs-prep-simulator"
    host, arch = host_kind()
    if expected := env.get("EXPECTED_ARCH"):
        assert arch == {"ARM64": "arm64", "X64": "amd64"}[expected], (host, arch, expected)
    launcher = (["pwsh", "-NoProfile", "-NonInteractive", "-File", r".\lfcs.ps1"]
                if host == "windows" else ["./bin/lfcs"])
    env = dict(env, PATH=os.pathsep.join((str(pathlib.Path(lima).parent), env["PATH"])))
    env.pop("LFCS_PROGRESS_PATH", None)

    def invoke(*args, **overrides):
        return subprocess.run([*launcher, *args], cwd=checkout, env={**env, **overrides},
                              capture_output=True, encoding="utf-8", timeout=60)

    help_result = invoke("help")
    assert help_result.returncode == 0 and "COMMAND [ARGS]" in help_result.stdout, help_result
    catalogue = invoke("list", "networking")
    assert catalogue.returncode == 0 and "networking-01" in catalogue.stdout, catalogue
    assert "operations-01" not in catalogue.stdout, catalogue
    suites = invoke("_complete", "mocks")
    assert suites.returncode == 0 and suites.stdout.strip() == "1 2 3 4 5 6", suites
    assert invoke("invalid-command").returncode == 2
    refused = invoke("progress", LFCS_PROGRESS_PATH=str(target / "outside-progress.json"))
    assert refused.returncode != 0 and "outside the candidate" in refused.stderr, refused
    assert not (target / "outside-progress.json").exists()
    doctor = invoke("doctor")
    assert doctor.returncode in (0, 1), doctor
    for line in (f"PASS: host {host}", f"PASS: CPU {arch}", "PASS: guest configurations",
                 "PASS: isolated Lima home", "PASS: Lima version "):
        assert any(row.startswith(line) for row in doctor.stdout.splitlines()), doctor
    assert "Preflight checks only" in doctor.stdout, doctor
    assert (doctor.returncode == 1) == any(row.startswith("FAIL:") for row in doctor.stdout.splitlines()), doctor
    assert not (checkout / ".lima").exists()
    assert sorted(p.name for p in (checkout / "state").iterdir()) == [".gitkeep"]
    # This empty test home contains only a forbidden override. The host guard
    # must refuse before calling Lima, even for a read-only inventory command.
    config = checkout / ".lima" / "_config"
    config.mkdir(parents=True)
    (config / "override.yaml").write_text("mounts: []\n", encoding="utf-8")
    refused = invoke("status")
    assert refused.returncode != 0 and "Refusing Lima configuration" in refused.stderr, refused
    print(doctor.stdout.rstrip())
    print(f"PASS: native {host}/{arch} launcher, doctor reporting and ZIP path with spaces")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci-release", action="store_true", help="Fetch pinned Lima into an isolated CI directory")
    parser.add_argument("--review-zip", type=pathlib.Path, help="Exercise the native launcher from a locally built and scanned ZIP")
    args = parser.parse_args()
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
        scratch = pathlib.Path(directory)
        lima = release_binary(scratch) if args.ci_release else shutil.which("limactl")
        if not lima:
            raise SystemExit("Lima is required to render the templates")
        env = dict(os.environ, LIMA_HOME=str(scratch / ".lima"))
        version = subprocess.check_output([lima, "--version"], text=True, env=env).strip()
        if args.ci_release and version != f"limactl version {RELEASE}":
            raise SystemExit(f"Unexpected CI Lima version: {version}")
        for template in sorted((ROOT / "lima").glob("*.yaml")):
            result = subprocess.check_output([lima, "template", "yq", "-", ". | @json"],
                                             input=template.read_bytes(), env=env)
            rendered = json.loads(result)
            assert not rendered.get("mounts") and not rendered.get("networks")
            assert not rendered.get("additionalDisks") and not rendered.get("blockDevices")
            image, = rendered["images"]
            assert image["digest"] == "sha256:" + integrity.EXPECTED[image["location"].rsplit("/", 1)[-1]]
            expected_arch = "x86_64" if "amd64" in template.name else "aarch64"
            assert rendered["arch"] == image["arch"] == expected_arch
            assert not rendered["ssh"]["loadDotSSHPubKeys"] and not rendered["ssh"]["forwardAgent"]
            assert rendered["ssh"]["localPort"] == 0
            assert rendered["portForwards"][0]["ignore"] and not rendered["portForwards"][0]["guestIPMustBeZero"]
            assert rendered["vmType"] == ("vz" if template.name in {"lfcs.yaml", "lfcs-special.yaml"} else "qemu")
        print(f"PASS: 14 local templates rendered with {version}")
        if args.review_zip:
            launcher_smoke(args.review_zip, scratch, lima, env)


if __name__ == "__main__":
    main()
