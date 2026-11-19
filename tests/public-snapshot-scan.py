#!/usr/bin/env python3
"""Scan the publishable snapshot and PDF for personal identifiers and common secrets."""
import argparse
import io
import pathlib
import re
import stat
import zipfile

from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP = {"tmp", "__pycache__", ".lima", ".git"}
patterns = {
    "personal-home": re.compile(r"/Users/[A-Za-z0-9._-]+"),
    "private-key": re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PRIVATE) PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "api-token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}
allowed_emails = {"student@lfcs.internal", "dirsrv@lfcs.service"}
def scan_file(path, data, findings):
    if path.suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        value = "\n".join(page.extract_text() for page in reader.pages)
        value += "\n" + "\n".join(str(x) for x in reader.metadata.values())
    else:
        try:
            value = data.decode("utf-8")
        except UnicodeDecodeError:
            findings.append((path, "unreviewed binary"))
            return
    for label, pattern in patterns.items():
        for match in pattern.finditer(value):
            if label == "email" and match.group() in allowed_emails:
                continue
            if path.name == "public-snapshot-scan.py" and label == "personal-home":
                continue
            findings.append((path, label))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=pathlib.Path)
    parser.add_argument("--ci-worktree", action="store_true", help="Scan tracked checkout files, without claiming Git-history review")
    args = parser.parse_args()
    findings = []
    count = 0
    if args.archive:
        with zipfile.ZipFile(args.archive) as release:
            names = set()
            for entry in release.infolist():
                path = pathlib.PurePosixPath(entry.filename)
                rel = pathlib.PurePosixPath(*path.parts[1:])
                if (path.is_absolute() or len(path.parts) < 2 or path.parts[0] != "lfcs-prep-simulator"
                    or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename
                    or entry.filename in names or stat.S_ISLNK(entry.external_attr >> 16)
                    or any(part in SKIP or part == ".env" or part.startswith(".env.") for part in rel.parts)
                    or (rel.parts[0] == "state" and rel.as_posix() != "state/.gitkeep")):
                    findings.append((path, "unsafe archive entry"))
                    continue
                names.add(entry.filename)
                count += 1
                scan_file(rel, release.read(entry), findings)
    else:
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if any(part in SKIP for part in rel.parts):
                continue
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                findings.append((rel, "redirected path"))
                continue
            if path.is_file():
                count += 1
                scan_file(rel, path.read_bytes(), findings)
        if (ROOT / ".git").exists() and not args.ci_worktree:
            findings.append((pathlib.Path(".git"), "unscanned Git history"))
    for path, label in sorted({(str(path), label) for path, label in findings}):
        print(f"FINDING {label}: {path}")
    if findings or not count:
        raise SystemExit(1)
    print(f"PASS: {count} files, including PDF text and metadata, with no personal identifiers or common secret patterns")
    if args.ci_worktree:
        print("Git history was outside this check.")


if __name__ == "__main__":
    main()
