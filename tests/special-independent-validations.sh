#!/usr/bin/env bash
set -euo pipefail
sid=${1:?scenario id required}
test "$(getenforce)" = Enforcing
test "$(cat /var/lib/lfcs-special/infrastructure-sentinel)" = lfcs-special-infrastructure-v1

case "$sid" in
  selinux-01)
    test "$(wc -l </tmp/lfcs-selinux-foundation)" -eq 5
    test "$(sed -n 1p /tmp/lfcs-selinux-foundation | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')" = Enforcing
    test "$(sed -n 2p /tmp/lfcs-selinux-foundation | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')" = targeted
    test "$(sed -n 3p /tmp/lfcs-selinux-foundation | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')" = httpd_sys_content_t
    test "$(sed -n 4p /tmp/lfcs-selinux-foundation | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')" = httpd_sys_content_t
    test "$(sed -n 5p /tmp/lfcs-selinux-foundation | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')" = httpd_t
    ;;
  selinux-02)
    matchpathcon -V /srv/lfcs-special/context-site/index.html
    curl -fsS http://127.0.0.1/ | grep -qx context-ready
    ;;
  selinux-03)
    semanage port -l | grep '^http_port_t' | grep -Eq '(^|[,[:space:]])8124([,[:space:]]|$)'
    curl -fsS http://127.0.0.1:8124/ | grep -qx port-ready
    ;;
  selinux-04)
    grep -qx httpd_t /tmp/lfcs-avc-diagnosis
    grep -qx user_home_t <(sed -n 2p /tmp/lfcs-avc-diagnosis)
    matchpathcon -V /srv/lfcs-special/avc-site/index.html
    curl -fsS http://127.0.0.1/ | grep -qx avc-ready
    ;;
  selinux-05)
    getsebool httpd_can_network_connect | grep -q -- '--> on'
    curl -fsS http://127.0.0.1/ | grep -qx boolean-ready
    ;;
  selinux-06)
    matchpathcon -V /srv/lfcs-special/transfer-site/index.html
    curl -fsS http://127.0.0.1/ | grep -qx transfer-ready
    ;;
  ldap-01)
    test "$(sed -n 3p /tmp/lfcs-ldap-foundation)" = 22001
    getent passwd directoryuser >/dev/null
    ;;
  ldap-02|ldap-03)
    getent passwd root >/dev/null; getent passwd student >/dev/null
    getent passwd directoryuser | grep -q '^directoryuser:.*:22001:22001:'
    getent group ldapops | grep -q '^ldapops:.*:22001:'
    ;;
  ldap-04)
    systemctl is-active --quiet dirsrv@lfcs.service
    getent passwd directoryuser >/dev/null
    ;;
  ldap-05)
    ! grep -q '^directoryuser:' /etc/passwd
    pamtester login directoryuser authenticate </var/lib/lfcs-special/credentials/directoryuser >/dev/null
    ;;
  *) exit 2 ;;
esac
