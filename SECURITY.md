# Security policy

This is a privileged Linux training environment. The threat boundary is the disposable Lima VM; scenario code performs root operations inside it. The `student` guest account has passwordless sudo. Do not use a guest for personal or production workloads. Do not expose its management SSH or lab services to untrusted networks.

The host launcher checks a checkout-local ownership record before shell access, reset, stop, or deletion. It refuses an existing Lima instance with the same name unless this checkout created it. The current implementation has not undergone a complete adversarial review and does not defend against a malicious local user who can modify the checkout or its state.

Start with a fresh checkout and fresh guest disks. Fedora bootstrap generates distinct directory-manager and practice-account passwords inside the guest. The files are readable only by root and the intended practice task shows how to read its guest-local password with sudo. Keep the generated values out of issue reports and source control.

The four guest images have pinned SHA-256 digests checked against signed publisher manifests. Offline refusal checks passed. Sequential startup, isolation and cleanup passed on the earlier M1 runtime. The current Fedora password path still needs live validation. Lima uses a per-user image cache, and guest access to host or LAN services depends on the network configuration. [Validation notes](docs/validation.md).

Report vulnerabilities privately to the maintainer. Include the scenario ID, host platform, versions, reproduction steps and impact. Leave credentials and learner data out of reports.
