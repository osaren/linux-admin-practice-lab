"""Authentic SELinux and directory-client scenarios hosted by lfcs-special."""

def S(id, minutes, title, requirements, skills, *, domain="operations", difficulty="medium", hints=None):
    return dict(
        id=id, day=4, domain=domain, host="lfcs-special", minutes=minutes,
        title=title, requirements=requirements, skills=skills,
        difficulty=difficulty,
        hints=hints or [
            "Reproduce the failure, then compare current state with the policy or provider's expected state.",
            "Use the subsystem's own diagnostic evidence; ordinary permissions and syntax are only part of the path.",
            "Make the narrow persistent repair, restart or reload only what is required, and validate the requested endpoint or identity.",
        ],
    )


SPECIAL_LABS = [
    S("selinux-01", 7, "Inspect real SELinux state", [
        "Create /tmp/lfcs-selinux-foundation with exactly five unlabeled lines: the current enforcement mode, loaded policy name, current context of /srv/lfcs-special/foundation/index.html, its policy-expected context, and the SELinux type of the running httpd process.",
        "Obtain the evidence with SELinux-aware inspection tools; leave SELinux enforcing and do not relabel the supplied content.",
    ], ["SELinux foundation", "security contexts", "matchpathcon"], difficulty="foundation"),
    S("selinux-02", 9, "Repair a persistent web-content context", [
        "Make http://127.0.0.1/ return context-ready from the supplied /srv/lfcs-special/context-site content while SELinux remains enforcing.",
        "Add a persistent file-context mapping for the entire content tree and apply it; the repair must survive restorecon and an httpd restart.",
    ], ["SELinux file contexts", "semanage fcontext", "restorecon"], difficulty="hard"),
    S("selinux-03", 9, "Label a non-standard web port", [
        "Make httpd bind TCP 8124 and serve port-ready at http://127.0.0.1:8124/ while SELinux remains enforcing.",
        "Persistently associate only TCP 8124 with the appropriate SELinux web-port type, then start and enable httpd.",
    ], ["SELinux port labels", "semanage port", "service validation"], difficulty="hard"),
    S("selinux-04", 10, "Diagnose an AVC denial", [
        "Diagnose why the supplied httpd site at http://127.0.0.1/ is denied even though Unix permissions are sufficient, and write the blocking SELinux source type, target type, and denied permission to /tmp/lfcs-avc-diagnosis as three unlabeled lines.",
        "Apply the narrow persistent labeling repair so the endpoint returns avc-ready; do not disable enforcement or install a custom allow module.",
    ], ["SELinux AVC analysis", "ausearch", "audit2why"], difficulty="hard"),
    S("selinux-05", 9, "Enable a bounded SELinux boolean", [
        "Repair the supplied reverse proxy so http://127.0.0.1/ returns boolean-ready from its local backend while SELinux remains enforcing.",
        "Use the existing SELinux boolean intended for outbound web-server connections, make the setting persistent, and leave httpd active and enabled.",
    ], ["SELinux booleans", "setsebool", "reverse proxy"], difficulty="hard"),
    S("selinux-06", 12, "Timed SELinux transfer", [
        "Restore the supplied web service so http://127.0.0.1/ returns transfer-ready after a service restart and after restorecon is reapplied to its content tree.",
        "SELinux must remain enforcing. Diagnose the policy mismatch independently and make only the narrow persistent repair; do not use chmod 777, chcon-only fixes, permissive mode, or a custom policy module.",
    ], ["SELinux timed troubleshooting", "persistent policy repair", "endpoint validation"], difficulty="hard"),

    S("ldap-01", 8, "Trace NSS through SSSD to LDAP", [
        "Create /tmp/lfcs-ldap-foundation with exactly six unlabeled lines: root's UID, student's UID, directoryuser's UID, directoryuser's primary GID, ldapops's GID, and directoryuser's identity provider name.",
        "Obtain the local and remote identities through NSS/SSSD tools; do not copy values from the task fixtures.",
    ], ["LDAP foundation", "NSS", "SSSD"], domain="users", difficulty="foundation"),
    S("ldap-02", 12, "Configure an LDAP identity client", [
        "Configure SSSD for anonymous identity lookup at ldap://127.0.0.1 using search base dc=lfcs,dc=internal so getent and id resolve directoryuser and ldapops.",
        "Keep root and student resolvable, protect the SSSD configuration with a root-owned non-world-readable mode, and leave SSSD active and enabled.",
    ], ["LDAP client configuration", "SSSD LDAP provider", "NSS preservation"], domain="users", difficulty="hard"),
    S("ldap-03", 10, "Repair an SSSD search-base fault", [
        "Repair the supplied directory client so getent passwd directoryuser, getent group ldapops, and id directoryuser succeed.",
        "Keep the working local identity sources, use ldap://127.0.0.1 and base dc=lfcs,dc=internal, clear stale client state, and leave SSSD active and enabled.",
    ], ["SSSD troubleshooting", "LDAP search base", "cache invalidation"], domain="users", difficulty="hard"),
    S("ldap-04", 10, "Timed directory-provider recovery", [
        "Restore directory-backed lookup so directoryuser and ldapops resolve through the configured client while root and student continue to resolve locally.",
        "Diagnose the unavailable provider, restore only the required service path, and prove the remote identity is returned by LDAP rather than a new local passwd or group entry.",
    ], ["LDAP timed troubleshooting", "provider lifecycle", "identity provenance"], domain="users", difficulty="hard"),
    S("ldap-05", 12, "Authenticate an LDAP identity through PAM", [
        "Make directoryuser resolvable through NSS and authenticatable through the system PAM login service. Read this guest's practice password with sudo cat /var/lib/lfcs-special/credentials/directoryuser.",
        "Keep local root and student lookup working, leave SSSD active and enabled, and do not create directoryuser in local passwd or shadow files.",
    ], ["PAM directory authentication", "SSSD authentication", "identity versus authentication"], domain="users", difficulty="hard"),
]
