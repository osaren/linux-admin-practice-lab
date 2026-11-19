# Native Windows 11 x86_64 installation

**Experimental. Live installation and scenario acceptance are NOT TESTED.** This path runs Linux guests in native Windows Lima/QEMU. Windows ARM64 is outside the initial target. WSL2 is a separate experimental route.

1. Use Windows 11 x86_64 on an Intel or AMD host, with firmware virtualization and the Windows Hypervisor Platform optional feature enabled. Feature changes and reboot may require an administrator. Use a standard PowerShell session to run the simulator. Review Microsoft's [WHP documentation](https://learn.microsoft.com/en-us/virtualization/api/hypervisor-platform/hypervisor-platform).
2. Install [Lima 2.3.0 or newer](https://lima-vm.io/docs/installation/), [QEMU 11.0.0 or newer](https://www.qemu.org/download/#windows), [Python 3.9 or newer](https://www.python.org/downloads/windows/), and Git if using a clone. Use native x86_64 tools. Download official archives or use a trusted package manager. Verify the upstream release checksum where provided. Put `limactl.exe`, `qemu-system-x86_64.exe`, and `qemu-img.exe` on PATH. The native Windows OpenSSH Client must provide `ssh.exe`, `scp.exe`, and `ssh-keygen.exe` in the same directory. Put the built-in Windows OpenSSH Client directory ahead of Git/MSYS SSH on PATH. The simulator does not need Windows OpenSSH Server, rsync, a shared directory, or a guest disk manager. [Lima QEMU requirements](https://lima-vm.io/docs/config/vmtype/qemu/).
3. Place the clean checkout in a short local NTFS path. Avoid a synced directory or network share. Preflight requires at least 12 GiB free and 6 GiB host RAM. Plan on 25 GiB free and at least 8 GiB RAM if you intend to use both guests.
4. Run the following in PowerShell after reviewing the scripts and accepting the experimental status.

```powershell
.\lfcs.ps1 doctor
.\lfcs.ps1 setup
.\lfcs.ps1 start
.\lfcs.ps1 status
.\lfcs.ps1 shell
```

If local policy blocks the PowerShell wrapper, use `py -3 -X utf8 .\lib\lfcs.py doctor` and substitute the same Python prefix for the remaining commands. Respect organization policy. PowerShell, POSIX Bash on macOS/Linux, and the Python entry point use identical command names and arguments. Use `.\lfcs.ps1` in place of the command prefix `./bin/lfcs` in examples. Run exercise commands inside the simulator shell.

```powershell
.\lfcs.ps1 lab operations-01
.\lfcs.ps1 grade operations-01
.\lfcs.ps1 reset operations-01
.\lfcs.ps1 stop
.\lfcs.ps1 stop lfcs-special
.\lfcs.ps1 uninstall
```

Uninstall prompts before removing simulator-owned VM files. Progress in `state` stays in the checkout. Lima's shared per-user download cache (under `%LocalAppData%\lima`) and host prerequisites remain installed. Stop on an ownership refusal and consult [troubleshooting](troubleshooting.md). See the [validation notes](validation.md) for the current evidence.
