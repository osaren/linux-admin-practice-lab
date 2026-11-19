# Validation and known limitations

## Prior full-project evidence

The earlier runtime recorded in `85b9990` passed sequential Ubuntu and Fedora live acceptance on an Apple Silicon M1 Mac with Lima 2.3.0/VZ. That run used local copies of the publisher images verified by SHA-256, a disposable checkout and Lima state, no host-directory mounts, and host-loopback blocking. It covered representative Ubuntu setup, grading and resets, Mini 1, Mocks 5 and 6, all 11 Fedora scenarios and owned-guest uninstall. Simultaneous guests, every Ubuntu scenario and a stock remote-image installation outside that environment were outside the run.

Hosted static checks passed for the earlier `85b9990` source on Apple Silicon macOS, Intel macOS, Ubuntu x86_64 and Windows x86_64. Those jobs checked the launchers, rendered templates and inspected packaging. Guest startup and acceptance on Intel Mac, native Linux, native Windows/WHPX and WSL2 remain unverified.

The current Fedora credential implementation generates distinct directory-manager and practice passwords in each fresh guest. Mocked checks verified generation, permissions, retry behavior and credential input formats. Live Fedora bootstrap and `ldap-05` grading and reset with this change remain unverified.

## Local checks

The following checks use a fresh checkout and leave guest startup to a separate test. Run from the checkout root.

```sh
bash tests/static-check.sh
python3 tests/platform-contract.py
python3 tests/host-safety-contract.py
python3 tests/mock-scoring-contract.py
python3 tests/mock-5-6-contract.py
python3 tests/reset-all-contract.py
python3 tests/image-integrity.py
python3 tests/render-templates.py
```

The mock contracts substitute scenario execution and grades. They verify sequencing and scoring, including resets and failure handling. The template check uses your installed Lima with a temporary Lima home. The image test above checks the configured pins. It takes `--download` for a full download and hash check. Lima validates the pinned digest when it retrieves a fresh image.

## Live verification on a disposable host

Review the [security notes](../SECURITY.md) first. Use a fresh checkout with a distinct Lima home, no learner data, and a network that you control. Follow your platform's installation guide. Check guest mounts, SSH management and host/network exposure before testing lab operations. Stage a representative task, record the initial grade, solve it, confirm the passing grade, then reset and confirm the baseline again. Repeat with a networking or storage task and a Fedora task. Progress through a complete mock session, stop both guests and confirm that uninstall removes only their resources. Record the exact checkout, host and guest versions and results, without including account names, local paths or credentials.
