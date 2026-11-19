# Architecture

`bin/lfcs` and `lfcs.ps1` resolve the checkout and call `lib/lfcs.py`. The Python CLI owns progress, exam sequencing, VM lifecycle, and routing. `lib/catalog.py`, `lib/extended_catalog.py`, and `lib/special_catalog.py` define 172 scenario records, five mini exams, and six mocks. The guest engines are `lib/scenario-engine.sh`, `lib/extended-engine.py`, and `lib/special-engine.py`; associated ownership helpers handle SSH, nginx, systemd, and NBD. `provisioning/` configures guests. `lib/topology.sh` constructs four namespaces inside Ubuntu; `lib/storage.sh` creates sparse loop-backed practice disks.

The host abstraction currently selects a Lima configuration by OS and CPU. macOS ARM64 uses VZ; macOS Intel, native Linux, WSL2 and Windows x86_64 select QEMU. This retains one CLI and one guest scenario engine. Linux and WSL2 execution remain unverified. Lima's official documentation lists Linux as a supported host with QEMU; nested QEMU/KVM behavior inside WSL2 requires real acceptance testing.

The Ubuntu guest contains `node1`, `node2`, `node3`, and `router1`. Each node has a private network namespace and a veth link to the router. The primary guest also contains the simulated block devices. Fedora is a separate guest for enforcing SELinux and LDAP/SSSD/PAM. Host mounts are disabled in the Lima configurations; project code is streamed into guests when needed.

The checkout-local `state/vm-ownership.json` records VM names created by this checkout. Guest operations and deletion require that record. `state/progress.json` stores learner results and is not copied into the public snapshot. `uninstall` retains learner state. Use a fresh checkout to keep the lab separate from other Lima projects.

## Cross-platform design decisions

The platform work follows this order.

1. Resolve host and architecture, select a pinned Linux template, and check prerequisites.
2. Route POSIX and PowerShell entry points through the same guarded Python CLI. Preserve existing scenario engines, grading, progress and sequencing.
3. Build one source archive and verify dispatch, template resolution, packaging and privacy on three CI operating systems.
4. Require isolated live installation and representative guest acceptance before marking a platform supported.

`lib/host_platform.py` contains host probes and Windows allocated disk accounting. On Windows the Python launcher uses a subprocess with inherited console streams for interactive SSH. It sends guest scripts as UTF-8 bytes with LF line endings, and supplies the Windows template on stdin to avoid interpreting a drive-letter path as a template URI. All guest execution is through Lima SSH. Bash, sudo, the namespaces and lab storage are inside the Linux guests.

Lima 2.3.0 supports native Windows QEMU and selects WHPX for native CPU execution. Its Windows QEMU driver requires QEMU 11 and its SSH code supports the native Windows OpenSSH tools. Lima manages guest disks, PID and socket files in the selected Lima home. The Windows path relies on the same Linux cloud-image format, two named instances, and the QEMU userspace network. Live evidence must confirm concurrent Ubuntu/Fedora startup, SSH and stdin transfer, separate disks, dynamic loopback management ports and stop/delete behavior. [Lima 2.3.0 QEMU driver](https://github.com/lima-vm/lima/blob/v2.3.0/pkg/driver/qemu/qemu.go) · [Native SSH implementation](https://github.com/lima-vm/lima/blob/v2.3.0/pkg/sshutil/sshutil.go).

HCS is experimental, uses VHDX, needs elevated host permissions and supports one running instance in the documented version. WSL2 adds a Linux host layer and would need demonstrated nested KVM for the existing fallback. Native QEMU is the initial Windows target. [HCS limitations](https://lima-vm.io/docs/config/vmtype/hcs/) · [Lima driver changes](https://lima-vm.io/docs/releases/breaking/).

The QA home and instance ownership record are separate from Lima's per-user image cache. Creation, startup and removal use a checkout-local network config with no system-managed networks. Templates allow only Lima's automatic loopback SSH management endpoint. The guest network can still reach host or LAN services depending on the backend and version. Host-account separation and an empty mount list do not establish network isolation. The supervised M1 run used Lima 2.3.0 with host-loopback blocking explicitly configured. The default templates disable mounts and automatic lab-service forwards. Check whether your guest can reach other host or LAN services before running privileged lab tasks. [Lima SSH behavior](https://lima-vm.io/docs/usage/ssh/) · [Networking](https://lima-vm.io/docs/config/network/user/) · [Versioned cache source](https://github.com/lima-vm/lima/blob/v2.3.0/pkg/downloader/downloader.go).
