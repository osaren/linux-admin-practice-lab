# Windows 11 with WSL2 installation

**Status: NOT TESTED.** This path requires a Windows 11 machine with a WSL2 distribution that exposes working KVM nested virtualization to the Linux environment. A WSL command succeeding is not evidence that the simulator works. No Windows networking or security setting is changed by the installer.

1. Confirm Windows 11, current WSL, a WSL2 distribution rather than WSL1, and virtualization enabled in firmware/Windows. Use `wsl --status` and `wsl --list --verbose` in PowerShell. Review any change to WSL, virtualization, or Windows settings yourself before applying it.
2. Inside the WSL2 Linux distribution, keep the checkout under `$HOME`, not `/mnt/c`. Install Python 3, Git, Lima 2.1.3 or newer, QEMU, OpenSSH client tools, and packages needed for `/dev/kvm`, following the native Linux guide and your distribution's package manager. WSL systemd is useful for diagnosis but the simulator's systemd exercises run in the nested guest.
3. Run `./bin/lfcs doctor`. It must identify WSL2, find QEMU, and confirm `/dev/kvm` access. If KVM is absent, stop; a software emulation fallback has not been validated for the workload.
4. Run `./bin/lfcs start`, `./bin/lfcs status`, `./bin/lfcs shell`, then the representative checks in [validation](validation.md). Verify namespace connectivity, loop/NBD/LVM, Docker, SELinux in Fedora, grading, reset, mock sequencing, and cleanup. These are guest capabilities and must be measured live.
5. Run `./bin/lfcs stop` and, when finished, `./bin/lfcs uninstall`. This removes owned nested guests and virtual disks only. Keep or delete the WSL checkout separately after backing up `state/`.

The WSL2 kernel and nested-virtualization behavior vary by Windows build and host hardware. Lima's native WSL2 driver is experimental. The simulator selects QEMU inside WSL2, where its performance and feature completeness remain unverified.

See the upstream documentation. [Microsoft WSL documentation](https://learn.microsoft.com/windows/wsl/), [Lima VM drivers](https://lima-vm.io/docs/config/vmtype/), [Lima WSL2 caveats](https://lima-vm.io/docs/config/vmtype/wsl2/).
