#!/usr/bin/env python3
"""Check pinned Lima image URLs and optionally hash the downloaded image bytes."""
import argparse
import hashlib
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED = {
    "ubuntu-24.04-minimal-cloudimg-arm64.img": "3dc8370d923978d4b610fa7964d1b36ba040eefb43198809ca5bc8ac51777b18",
    "ubuntu-24.04-minimal-cloudimg-amd64.img": "406630c08b5e545fcc7209854b129d47e3af822db128c9f19336593b5a2d3fe0",
    "Fedora-Cloud-Base-Generic-43-1.6.aarch64.qcow2": "66031aea9ec61e6d0d5bba12b9454e80ca94e8a79c913d37ded4c60311705b8b",
    "Fedora-Cloud-Base-Generic-43-1.6.x86_64.qcow2": "846574c8a97cd2d8dc1f231062d73107cc85cbbbda56335e264a46e3a6c8ab2f",
}
NGINX_INDEX = "sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11"


def pinned_images():
    provisioning = (ROOT / "provisioning/upgrade-v2.sh").read_text()
    if f"nginx@{NGINX_INDEX}" not in provisioning or "docker pull nginx:alpine" in provisioning:
        raise SystemExit("NGINX guest image is not pinned to the reviewed OCI index")
    configs = sorted((ROOT / "lima").glob("*.yaml"))
    if len(configs) != 14:
        raise SystemExit(f"expected 14 VM configs; found {len(configs)}")
    urls = {}
    for config in configs:
        text = config.read_text()
        locations = re.findall(r"^\s+- location: (https://\S+)$", text, re.M)
        digests = re.findall(r'^\s+digest: "sha256:([0-9a-f]{64})"$', text, re.M)
        if len(locations) != 1 or len(digests) != 1:
            raise SystemExit(f"image source/digest missing or ambiguous: {config.name}")
        url, digest = locations[0], digests[0]
        name = url.rsplit("/", 1)[-1]
        if name not in EXPECTED or EXPECTED[name] != digest:
            raise SystemExit(f"unexpected image or digest: {config.name}")
        if name.startswith("ubuntu-") and "/release-20261105/" not in url:
            raise SystemExit(f"Ubuntu release URL is mutable: {config.name}")
        if name.startswith("Fedora-") and "/releases/43/Cloud/" not in url:
            raise SystemExit(f"Fedora release URL is unexpected: {config.name}")
        if name in urls and urls[name] != url:
            raise SystemExit(f"inconsistent URL for {name}")
        urls[name] = url
    if set(urls) != set(EXPECTED):
        raise SystemExit("not every image architecture is represented")
    return urls


def download_and_verify(name, url):
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=45) as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    actual = digest.hexdigest()
    if actual != EXPECTED[name]:
        raise SystemExit(f"SHA-256 mismatch for {name}: expected {EXPECTED[name]}, got {actual}")
    print(f"PASS: SHA-256 {name} ({size} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="Stream and hash all four images")
    args = parser.parse_args()
    images = pinned_images()
    print(f"PASS: {len(images)} unique pinned images across 14 Lima configs")
    if args.download:
        for name, url in images.items():
            download_and_verify(name, url)
