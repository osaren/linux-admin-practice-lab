# Troubleshooting

- `doctor` reports an unowned instance: the name already belongs to another Lima installation or checkout. Keep it intact. Use an isolated machine or manually resolve ownership after verifying the VM; do not fabricate an ownership record.
- QEMU missing: install the platform package and rerun `doctor`.
- KVM inaccessible on Linux/WSL2: enable virtualization and arrange user access to `/dev/kvm`; restart the shell or WSL distribution as required. No software emulation fallback is validated.
- Windows WHPX check fails: confirm a native QEMU 11+ build, firmware virtualization and the Windows Hypervisor Platform feature. See the [native Windows guide](install-windows.md) for the OpenSSH and PATH checks.
- WSL1 detected: upgrade the distribution to WSL2. Keep this checkout under the Linux home directory, not `/mnt/c`.
- Namespace or storage health fails: stop work, preserve `state/progress.json`, and run `./bin/lfcs status`. On an owned disposable guest, `./bin/lfcs reset-all` can rebuild the baseline. Report repeated failures with the scenario ID and guest logs.
- Image download fails: verify the URL and the publisher's checksum. Do not substitute an arbitrary VM image.
- `uninstall` retains progress by design. Back up `state/` before deleting the checkout if you want to preserve scores and notes.
