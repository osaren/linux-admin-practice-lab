#!/usr/bin/env python3
"""Verify publisher signatures and compare authenticated manifests with image pins."""
import importlib.util
import pathlib
import re
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("image_integrity", ROOT / "tests/image-integrity.py")
integrity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integrity)
UBUNTU = "D2EB44626FDDC30B513D5BB71A5D6C4C7DB87C81"
FEDORA = "C6E7F081CF80E13146676E88829B606631645531"


def download(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        if not response.geturl().startswith("https://"):
            raise SystemExit("Refusing non-HTTPS provenance data")
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise SystemExit("Unexpectedly large provenance data")
    return data


def verify_signer(status, fingerprint):
    for line in status.decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if fields[:2] == ["[GNUPG:]", "VALIDSIG"] and fingerprint in (fields[2], fields[-1]):
            return
    raise SystemExit(f"Expected publisher signing fingerprint {fingerprint} was absent")


def main():
    if not shutil.which("gpg"):
        raise SystemExit("GnuPG is required to verify publisher signatures")
    images = integrity.pinned_images()
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="provenance-", dir=ROOT / "tmp") as scratch:
        path = pathlib.Path(scratch)
        gpg = ["gpg", "--no-options", "--homedir", scratch, "--batch", "--no-auto-key-retrieve"]
        for key_url in (f"https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x{UBUNTU}",
                        "https://fedoraproject.org/fedora.gpg"):
            subprocess.run([*gpg, "--import"], input=download(key_url), check=True, capture_output=True)
        ubuntu_dir = next(url.rsplit("/", 1)[0] for name, url in images.items() if name.startswith("ubuntu"))
        sums, signature = path / "SHA256SUMS", path / "SHA256SUMS.gpg"
        sums.write_bytes(download(f"{ubuntu_dir}/SHA256SUMS"))
        signature.write_bytes(download(f"{ubuntu_dir}/SHA256SUMS.gpg"))
        result = subprocess.run([*gpg, "--status-fd", "1", "--verify", str(signature), str(sums)],
                                check=True, capture_output=True)
        verify_signer(result.stdout, UBUNTU)
        for name, url in images.items():
            if name.startswith("ubuntu"):
                manifest = sums.read_text(encoding="utf-8")
                pattern = rf"(?mi)^([a-f0-9]{{64}})\s+\*?{re.escape(name)}\s*$"
            else:
                arch = "x86_64" if ".x86_64." in name else "aarch64"
                manifest_url = f"{url.rsplit('/', 1)[0]}/Fedora-Cloud-43-1.6-{arch}-CHECKSUM"
                result = subprocess.run([*gpg, "--status-fd", "2", "--decrypt"],
                                        input=download(manifest_url), check=True, capture_output=True)
                verify_signer(result.stderr, FEDORA)
                manifest = result.stdout.decode("utf-8")
                pattern = rf"(?mi)^SHA256 \({re.escape(name)}\) = ([a-f0-9]{{64}})\s*$"
            if re.findall(pattern, manifest) != [integrity.EXPECTED[name]]:
                raise SystemExit(f"Authenticated manifest does not match the pin for {name}")
            print(f"PASS: signed publisher manifest matches {name}")


if __name__ == "__main__":
    main()
