#!/usr/bin/env python3
"""Offline native-runner contract. Simulated guest I/O, NOT Linux-state QA."""
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
from collections import Counter
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
EXPECTED = {
    "5": "systemd-08 nmcli-02 mount-02 text-06 docker-02 ssh-match-01 lvm-03 sudo-03 process-02 iptables-06 nfs-01 archive-02 opsusers-08 nginx-03 storage-06 permissions-02 env-03 git-02".split(),
    "6": "systemd-04 networking-12 storage-02 find-05 cron-03 advanced-05 nbd-01 limits-02 timesync-01 advanced-06 storage-04 text-03 docker-01 nginx-02 autofs-01 archive-01 usermod-04 git-01".split(),
}


class GuestDouble:
    def __init__(self):
        self.active = None
        self.passed = 0
        self.calls = []

    def engine(self, mode, sid, capture=False):
        self.calls.append((mode, sid))
        if mode == "setup":
            assert self.active is None, "previous task was not cleaned"
            self.active, self.passed = sid, 0
        elif mode == "reset":
            assert self.active in (None, sid)
            self.active, self.passed = None, 0
        elif mode == "grade":
            assert self.active == sid, "graded the wrong scenario"
        else:
            raise AssertionError(mode)
        return SimpleNamespace(stdout="\n".join(
            f"{'PASS' if n < self.passed else 'FAIL'}|contract clause {n}"
            for n in range(4)))


def load(progress, guest):
    spec = importlib.util.spec_from_file_location("native_mock_contract", ROOT / "lib/lfcs.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    cli.PROGRESS = progress
    cli.engine = guest.engine
    cli.require_running = lambda *a, **k: None
    cli.ensure_topology = lambda: None
    cli.ensure_student_admin = lambda *a, **k: None
    # Any accidental real command is a test failure, never a guest mutation.
    def forbidden(*args, **kwargs):
        raise AssertionError("offline test attempted external I/O")
    cli.run = forbidden
    return cli


def capture(fn, args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(args)
    return out.getvalue()


def reject(fn, args, phrase):
    try:
        capture(fn, args)
    except SystemExit as exc:
        assert phrase in str(exc), str(exc)
    else:
        raise AssertionError(f"accepted invalid request: {args}")


def exercise(folder, kind, number, partial=False):
    guest = GuestDouble()
    progress = folder / f"{kind}-{number}-{partial}.json"
    cli = load(progress, guest)
    ids = (cli.MOCKS if kind == "mock" else cli.MINIS)[number]
    # Sentinels prove writes preserve unrelated history and sessions.
    sentinel = {"labs": {"outside-task": {"attempts": 7, "best_score": 64}},
                "mistakes": [], "mocks": {"unrelated": {"scores": {"x": 64}}},
                "custom": {"retain": True}}
    cli.save_progress(sentinel)
    output = capture(cli.COMMANDS[kind], [number])
    assert guest.calls == [("setup", ids[0]), ("grade", ids[0])]
    assert f"{kind.upper()} PRACTICE SESSION {number}" in output
    if kind == "mock":
        assert "120 minutes" in output and "Tasks: 18" in output
        assert f"Enter host: ./bin/lfcs shell {cli.BY_ID[ids[0]]['host']}" in output
    for sid in ids:
        assert all(r in output for r in cli.BY_ID[sid]["requirements"])
    expected = {}
    key = "mocks" if kind == "mock" else "minis"
    started = cli.progress_data()[key][number]["started"]
    dispatch_checks = 0
    for index, sid in enumerate(ids):
        assert guest.active == sid
        current = cli.progress_data()[key][number]
        assert current["index"] == index and current["scores"] == expected
        if kind == "mock" and number in EXPECTED and not partial:
            # Same public staging path/baseline metadata; not semantic Linux proof.
            standalone_guest = GuestDouble()
            standalone = load(folder / f"standalone-{number}-{index}.json", standalone_guest)
            capture(standalone.cmd_lab, [sid])
            assert standalone_guest.calls == [("setup", sid), ("grade", sid)]
            record = cli.progress_data()["labs"][sid]
            other = standalone.progress_data()["labs"][sid]
            for field in ("baseline_checks", "baseline_score", "hints_current"):
                assert record[field] == other[field]
            dispatch_checks += 1
        # Reload the module to simulate a fresh process continuing saved session.
        if index in (3, 9):
            before = progress.read_bytes()
            cli = load(progress, guest)
            assert progress.read_bytes() == before
            assert cli.progress_data()[key][number]["started"] == started
        guest.passed = (0 if index == 0 else 2) if partial and index < 2 else 4
        expected[sid] = guest.passed * 25
        start = len(guest.calls)
        output = capture(cli.COMMANDS[f"{kind}-grade"], [number])
        calls = [("grade", sid), ("reset", sid)]
        if index + 1 < len(ids):
            nxt = ids[index + 1]
            calls += [("setup", nxt), ("grade", nxt)]
            assert f"Next staged task: {index+2}" in output
            assert all(r in output for r in cli.BY_ID[nxt]["requirements"])
            assert f"Host: {cli.BY_ID[nxt]['host']}" in output
        assert guest.calls[start:] == calls
        assert all(word in output for word in ("Baseline:", "Final:", "Improvement:", "Practice final-state score:", "Score:"))
        rec = cli.progress_data()["labs"][sid]
        assert rec["attempts"] == 1 and rec["latest_score"] == expected[sid]
    data = cli.progress_data()
    session = data[key][number]
    assert session["scores"] == expected and session["index"] == len(ids)
    assert guest.active is None
    raw = round(sum(expected.values()) / len(ids))
    assert f"LAB RAW SCORE: {raw}%" in output
    weights = dict(operations=.25, networking=.25, storage=.20, commands=.20, users=.10)
    grouped = {}
    for sid in ids:
        grouped.setdefault(cli.BY_ID[sid]["domain"], []).append(expected[sid])
    domains = {d: round(sum(v)/len(v)) for d, v in grouped.items()}
    if weights.keys() <= domains.keys():
        weighted = round(sum(domains[d]*w for d, w in weights.items()))
        assert f"DOMAIN-WEIGHTED PRACTICE SCORE: {weighted}%" in output
    else:
        assert "DOMAIN-WEIGHTED PRACTICE SCORE: UNAVAILABLE" in output
    labels = dict(operations="Operations & Deployment", networking="Networking", storage="Storage", commands="Essential Commands", users="Users & Groups")
    for domain, result in domains.items():
        assert f"{labels.get(domain,domain.title()):<24} {result:>3}%" in output
    for q, sid in enumerate(ids, 1):
        assert f"Q{q:<2} {expected[sid]:>3}%  {sid}" in output
    assert "Elapsed:" in output
    assert data["labs"]["outside-task"] == sentinel["labs"]["outside-task"]
    assert data["mocks"]["unrelated"] == sentinel["mocks"]["unrelated"]
    assert data["custom"] == sentinel["custom"]
    reject(cli.COMMANDS[f"{kind}-grade"], [number], "complete")
    if kind == "mock":
        # Restart is existing behavior; it is not a resume command.
        capture(cli.cmd_mock, [number])
        assert cli.progress_data()[key][number]["index"] == 0
        assert cli.progress_data()[key][number]["scores"] == {}
        assert cli.progress_data()["labs"][ids[0]]["attempts"] == 1
    print(f"PASS offline {kind}-{number} partial={partial}: {len(ids)} transitions raw={raw}%; standalone dispatch checks={dispatch_checks}")


def main():
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lfcs-native-mocks-", dir=ROOT / "tmp") as path:
        folder = pathlib.Path(path)
        cli = load(folder / "validation.json", GuestDouble())
        assert set(cli.MOCKS) == {str(n) for n in range(1, 7)}
        for number, ids in EXPECTED.items():
            assert cli.MOCKS[number] == ids and len(set(ids)) == 18
            assert Counter(cli.BY_ID[s]["domain"] for s in ids) == dict(operations=4, networking=4, storage=4, commands=4, users=2)
            reject(cli.cmd_mock_grade, [number], "not active")
        for fn in (cli.cmd_mock, cli.cmd_mock_grade):
            for args in ([], ["0"], ["7"], ["-1"], ["05"], ["abc"]):
                reject(fn, args, "Usage:")
        for number in cli.MOCKS:
            exercise(folder, "mock", number)
        for number in EXPECTED:
            exercise(folder, "mock", number, partial=True)
        for number in cli.MINIS:
            exercise(folder, "mini", number)
    print("PASS: 13 offline suite lifecycles, 179 grades; 36 standalone staging-dispatch checks.")
    print("NOT TESTED: actual guest state equivalence, canonical Linux grader results, live cleanup or health.")


if __name__ == "__main__":
    main()
