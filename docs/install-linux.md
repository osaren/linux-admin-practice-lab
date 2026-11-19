# Native Linux installation

**Experimental. Live installation and scenario acceptance are NOT TESTED.** Initial host targets are Ubuntu 24.04 LTS or later and Fedora 43 or later on x86_64. ARM64 configurations exist for separate evaluation. Ubuntu and Fedora lab guests are provisioned independently of the host distribution.

1. Use a host with hardware virtualization, at least 6 GiB RAM and 12 GiB free disk, and an accessible `/dev/kvm`. Plan on 8 GiB RAM for testing both guests. An administrator may need to enable firmware virtualization or grant the intended account device access. Use a normal user login for the simulator.
2. Review prerequisites before installing. Ubuntu x86_64 packages include `python3 qemu-system-x86 qemu-utils ovmf openssh-client git`. Fedora x86_64 packages include `python3 qemu-system-x86 qemu-img edk2-ovmf openssh-clients git`. Use APT or DNF as appropriate. ARM64 uses the distro's AArch64 QEMU system package and matching UEFI firmware. Check `qemu-system-x86_64 --version` or `qemu-system-aarch64 --version`, and `qemu-img --version`. The minimum QEMU version is 6.2.0.
3. Install Lima 2.1.3 or newer using a trusted distro package or its official verified release archive. Check the version before continuing. Lima 2.1.3 includes the QEMU guest-agent security fix. [Lima installation](https://lima-vm.io/docs/installation/) · [QEMU requirements](https://lima-vm.io/docs/config/vmtype/qemu/) · [Upstream security advisory](https://github.com/lima-vm/lima/security/advisories/GHSA-2j9v-p4xj-cjw2).
4. From a clean checkout on a local filesystem, run:

```sh
./bin/lfcs doctor
./bin/lfcs setup
./bin/lfcs start
./bin/lfcs status
./bin/lfcs shell
```

`doctor` opens and closes the KVM device without creating a VM. If it cannot open it, have the administrator review the device owner, group and the login's group memberships. The simulator requires KVM here. The first start downloads a pinned Ubuntu image and installs packages inside Ubuntu. The Fedora guest starts separately for SELinux and LDAP/SSSD. Stop both guests with `./bin/lfcs stop` and `./bin/lfcs stop lfcs-special`. Use `./bin/lfcs uninstall` for prompted removal of the checkout's VMs. See the [validation notes](validation.md).
