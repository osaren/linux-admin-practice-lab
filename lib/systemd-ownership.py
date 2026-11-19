#!/usr/bin/env python3
"""Reset only the systemd service artifacts owned by LFCS scenarios."""

import argparse
import pathlib
import shutil
import subprocess

if not pathlib.Path('/usr/local/lib/lfcs/verify-guest.py').is_file() or subprocess.run(['/usr/local/lib/lfcs/verify-guest.py'], capture_output=True).returncode:
    raise SystemExit('LFCS systemd helper: candidate guest marker missing')


SLEEPER_UNIT = """[Unit]
Description=LFCS practice sleeper
[Service]
ExecStart=/usr/bin/sleep infinity
Restart=on-failure
[Install]
WantedBy=multi-user.target
"""

OWNERS = {
    "operations-01": {
        "units": ("acorn-api",),
        "paths": ("/usr/local/bin/acorn-api", "/run/acorn-api.ready"),
    },
    "operations-02": {
        "units": ("report-writer",),
        "paths": ("/usr/local/bin/report-writer", "/var/log/report-writer.log"),
    },
    "operations-03": {
        "units": ("cedar-worker",),
        "paths": (
            "/usr/local/bin/cedar-worker-v1",
            "/usr/local/bin/cedar-worker-v2",
            "/run/cedar-version",
        ),
    },
    "systemd-04": {
        "units": ("alder-worker",),
        "paths": ("/usr/local/bin/alder-worker", "/run/alder-user"),
        "users": ("svc-alder",),
    },
    "systemd-05": {
        "units": ("pine-api",),
        "paths": ("/usr/local/bin/pine-api", "/run/pine-mode"),
    },
    "systemd-06": {
        "units": ("juniper-agent",),
        "paths": ("/usr/local/bin/juniper-agent", "/run/juniper-ready"),
    },
    "systemd-07": {
        "units": ("spruce-data", "spruce-web"),
        "paths": (
            "/usr/local/bin/spruce-data",
            "/usr/local/bin/spruce-web",
            "/run/spruce-data-ready",
            "/run/spruce-web-ready",
        ),
    },
    "systemd-08": {
        "units": ("hemlock-job",),
        "paths": (
            "/usr/local/bin/hemlock-job",
            "/etc/lfcs-lab/hemlock.env",
            "/run/hemlock-result",
        ),
    },
    "opsusers-11": {
        "units": ("mint-agent",),
        "paths": ("/usr/local/bin/mint-agent",),
    },
    "day1-mini": {
        "units": ("lfcs-sleeper",),
        "paths": (),
        "baseline_units": {"lfcs-sleeper": SLEEPER_UNIT},
    },
}


def run(*args):
    subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=False)


def remove_path(raw_path):
    path = pathlib.Path(raw_path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def reset(owner):
    spec = OWNERS[owner]
    baselines = spec.get("baseline_units", {})
    for unit in spec["units"]:
        service = f"{unit}.service"
        run("systemctl", "unmask", service)
        run("systemctl", "disable", "--now", service)
        remove_path(f"/etc/systemd/system/{service}")
        remove_path(f"/etc/systemd/system/{service}.d")
        remove_path(f"/run/systemd/system/{service}")
        remove_path(f"/run/systemd/system/{service}.d")
        if unit in baselines:
            path = pathlib.Path(f"/etc/systemd/system/{service}")
            path.write_text(baselines[unit])
            path.chmod(0o644)
    for path in spec["paths"]:
        remove_path(path)
    run("systemctl", "daemon-reload")
    for unit in spec["units"]:
        run("systemctl", "reset-failed", f"{unit}.service")
    for user in spec.get("users", ()):
        run("userdel", "-r", user)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("reset", "reset-all"))
    parser.add_argument("scenario", nargs="?")
    args = parser.parse_args()
    if args.command == "reset":
        if args.scenario not in OWNERS:
            parser.error("reset requires a known service-owning scenario")
        reset(args.scenario)
    else:
        for owner in OWNERS:
            reset(owner)


if __name__ == "__main__":
    main()
