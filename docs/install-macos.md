# macOS installation

**Status: supervised sequential M1 acceptance passed on the earlier `85b9990` runtime.** The tested setup used Lima 2.3.0/VZ, digest-checked local images, isolated state, no host mounts and host-loopback blocking. The new Fedora password path, Intel macOS, simultaneous guests and installation outside that tested setup remain unverified. [Tested configuration and evidence](validation.md).

1. Use macOS with at least 6 GiB RAM and 12 GiB free disk. Enable the host virtualization facilities normally provided by macOS. Install Python 3.9 or newer and Lima 2.0 or newer from trusted packages. On Apple Silicon, use Lima 2.3.0 or newer for the documented VZ isolation option. The supervised M1 run used Lima 2.3.0. On Intel, require Lima 2.1.3 or newer and QEMU 8.2.1 or newer; the configuration uses QEMU. Homebrew commands, after reviewing package changes: `brew install python lima` and, for Intel, `brew install qemu`.
2. Clone the repository into a writable local directory. Quote paths containing spaces.
   On Apple Silicon with Lima 2.3.0 or newer, add the following to both `lima/lfcs.yaml` and `lima/lfcs-special.yaml` before first start to match the host-loopback setting in the supervised run. This blocks access through the VZ host-loopback address. Check LAN reachability separately. [Lima 2.3.0 template reference](https://github.com/lima-vm/lima/blob/v2.3.0/templates/default.yaml).

   ```yaml
   networkOpts:
     hostLoopback: false
   ```

3. Run `./bin/lfcs doctor`. Resolve every failure before `./bin/lfcs start`. `doctor` does not download or install anything.
4. Run `./bin/lfcs start`, then `./bin/lfcs status` and `./bin/lfcs shell`. First start downloads an Ubuntu image and installs packages **inside the guest**. A SELinux or LDAP task later creates the Fedora guest.
5. Test `./bin/lfcs lab operations-01`, grade, reset, then `./bin/lfcs stop`. Use the [validation notes](validation.md) to compare your results with the supervised run.

`./bin/lfcs uninstall` removes only VMs recorded as owned by this checkout after confirmation. It retains progress and host packages. The simulator keeps its VMs in `./.lima`, separate from any existing user Lima instances. Use an isolated practice host or account and network. Lima shares the per-user image cache, and an empty mount list does not block guest access to host or LAN services.

See the upstream documentation. [Lima installation](https://lima-vm.io/docs/installation/), [VM drivers](https://lima-vm.io/docs/config/vmtype/), [QEMU driver](https://lima-vm.io/docs/config/vmtype/qemu/).
