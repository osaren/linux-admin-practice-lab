# Linux Admin Practice Lab

**An unofficial, hands-on simulator for Linux Foundation Certified System Administrator (LFCS) preparation.**

I built this personal project with Codex to practise Linux administration in a repeatable lab and share it with other learners. You work inside Linux virtual machines, make changes to the system and use the simulator to check the resulting state.

Practice scores measure your work in this lab. They have no official certification status and do not predict exam outcomes or establish exam equivalence.

**Independent project.** This lab has no affiliation with, sponsorship from, or endorsement by The Linux Foundation. LFCS and the certification name refer to The Linux Foundation’s certification.

## What’s included

- 172 Linux administration scenarios with optional hints and reference solutions.
- Automated grading that checks the resulting system state and can award partial practice credit.
- Exercise resets so you can retry a task without rebuilding the entire lab.
- Five mini practice sessions and six mock exams for structured practice.
- Ubuntu and Fedora labs for work with services, storage, networking, SELinux and LDAP/SSSD.
- Local progress tracking so you can revisit your results and areas for practice.
- Lima configurations and provisioning scripts that recreate the lab using upstream images.

## How the lab works

The host launcher runs a shared Python CLI and uses Lima to manage the Linux guests.

- **Ubuntu 24.04** hosts most exercises. Four network namespaces (`node1`, `node2`, `node3` and `router1`) simulate multiple hosts, and virtual practice disks support storage tasks.
- **Fedora** provides a separate guest for exercises that need SELinux or LDAP/SSSD. The launcher starts Fedora when a task requires it.

The `lima/` templates pin upstream images by SHA-256 and disable host-directory mounts. The scripts in `provisioning/` install packages and configure the guests. The code in `lib/` handles staging, grading and resets. The repository includes source and configuration. Lima retrieves the operating-system images when needed. [Architecture guide](docs/architecture.md).

## Requirements

Use a writable local checkout, Python 3.9 or newer, Lima and OpenSSH client tools. Install the prerequisites and follow the virtualization and isolation instructions for your host. [macOS](docs/install-macos.md) · [Native Linux](docs/install-linux.md) · [Windows 11](docs/install-windows.md) · [WSL2](docs/install-wsl2.md).

| Resource | Requirement |
|---|---|
| Host memory | Preflight requires at least 6 GiB RAM. |
| Free disk | Preflight requires at least 12 GiB free. Plan on **25 GiB or more** if you intend to use both guests. Image downloads, package installation and sparse disk growth use additional space. |
| Per guest | Two vCPUs, 2 GiB RAM and a sparse disk with 12 GiB logical capacity. |
| Network | Internet access for the first image downloads and guest package installation. |

Native Linux and WSL2 require working KVM. Intel macOS and native Windows use QEMU with the relevant platform accelerator. Apple Silicon uses Lima’s VZ driver. The platform guides list the required versions and setup steps. Run privileged exercises inside disposable guests in an isolated practice environment. [Security notes](SECURITY.md).

## Quick start

Clone the repository and enter its directory:

```sh
git clone https://github.com/osaren/linux-admin-practice-lab.git
cd linux-admin-practice-lab
```

From the repository root on macOS or Linux:

```sh
./bin/lfcs doctor
./bin/lfcs setup
./bin/lfcs start
./bin/lfcs status
```

In native Windows PowerShell:

```powershell
.\lfcs.ps1 doctor
.\lfcs.ps1 setup
.\lfcs.ps1 start
.\lfcs.ps1 status
```

`doctor` and `setup` check prerequisites. Resolve any reported failures before starting a guest. `start` creates and provisions Ubuntu if needed. On the first run, Lima downloads the pinned image and the simulator installs packages inside the guest. A task requiring Fedora starts that guest automatically. You can also start it with `./bin/lfcs start lfcs-special`. For all examples below, use the same arguments after `.\lfcs.ps1` on native Windows.

## Practise an exercise

List the tasks and pick one of the displayed IDs. In this example, you repair a systemd service:

```sh
./bin/lfcs list
./bin/lfcs lab operations-01
./bin/lfcs shell
# Complete the task inside the guest, then exit the shell.
./bin/lfcs grade operations-01
./bin/lfcs reset operations-01
```

`lab` shows the task and its target host. For a task in a network namespace, pass the displayed name to `shell`, for example `./bin/lfcs shell node2`. Use `./bin/lfcs hint operations-01` or `./bin/lfcs solution operations-01` for help. Grading checks the system state and shows which requirements passed. Reset restores that exercise’s managed baseline so you can try again.

## Mini sessions and mock exams

Start Mini 1 and grade each task after you complete it:

```sh
./bin/lfcs mini 1
./bin/lfcs mini-grade 1
```

Or start Mock 5 and use its grade command:

```sh
./bin/lfcs mock 5
./bin/lfcs mock-grade 5
```

Complete the active task and run the session’s grade command to record the result and advance. Finish a session before starting another. Progress is stored locally under `state/`. Use `./bin/lfcs progress` to see your results and `./bin/lfcs help` for all commands.

## Managing the lab

```sh
./bin/lfcs stop
./bin/lfcs stop lfcs-special
```

`./bin/lfcs reset-all` asks before restoring lab-owned runtime state. `./bin/lfcs uninstall` asks before deleting the guests and disks owned by this checkout and preserves learner progress and host dependencies. Review the prompts before resetting or removing anything. Lima manages its per-user image cache separately.

Guest access to services on the host or LAN depends on your network configuration. Use a network you control and keep personal data out of the guests. [Security notes](SECURITY.md) · [Troubleshooting](docs/troubleshooting.md).

## Testing and platform limitations

| Platform | Evidence |
|---|---|
| Apple Silicon macOS (M1) | Earlier runtime `85b9990` passed supervised sequential Ubuntu and Fedora acceptance with Lima 2.3.0/VZ, verified local images, isolated state, host mounts disabled and host-loopback blocking. Coverage included representative labs, grading, resets, Mini 1, Mocks 5 and 6, and cleanup. |
| Intel macOS, Ubuntu x86_64, Windows x86_64 | Hosted static checks passed for `85b9990` on these hosts and on Apple Silicon. Live installation and guest acceptance on Intel Mac, native Linux and Windows/WHPX remain unverified. |
| Other Linux hosts and Windows 11 with WSL2 | Live installation and guest acceptance remain unverified. |

The earlier live run covered one guest at a time and a subset of the catalogue. The current Fedora credential-generation changes passed mocked checks. Fresh Fedora bootstrap and `ldap-05` grading and reset with those changes remain unverified live. [Validation details](docs/validation.md).

When reporting a platform issue or broken exercise, include the host platform, scenario ID and steps to reproduce the problem. Leave passwords, private keys and learner data out of reports.

## License

The [MIT License](LICENSE), copyright © 2026 osaren, covers the original project code, configurations, exercises, solutions, fixtures, tests and documentation. Upstream tools, distributions, packages and downloaded images retain their own terms. [Lima](https://github.com/lima-vm/lima/blob/v2.3.0/LICENSE) · [QEMU](https://www.qemu.org/docs/master/about/license.html) · [Ubuntu](https://canonical.com/legal/intellectual-property-policy) · [Fedora](https://docs.fedoraproject.org/en-US/legal/).
