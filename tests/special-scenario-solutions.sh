#!/usr/bin/env bash
set -euo pipefail
sid=${1:?scenario id required}

configure_sssd() {
  install -d -m 0755 /etc/sssd
  cat >/etc/sssd/sssd.conf <<'EOF'
[sssd]
services = nss, pam
domains = lfcs

[domain/lfcs]
id_provider = ldap
auth_provider = ldap
ldap_uri = ldap://127.0.0.1
ldap_search_base = dc=lfcs,dc=internal
ldap_schema = rfc2307
ldap_id_use_start_tls = false
ldap_tls_reqcert = never
cache_credentials = false
enumerate = false
EOF
  chmod 0600 /etc/sssd/sssd.conf
  systemctl enable --now sssd
  sss_cache -E || true
  systemctl restart sssd
}

case "$sid" in
  selinux-01)
    current=$(stat -c %C /srv/lfcs-special/foundation/index.html | cut -d: -f3)
    expected=$(matchpathcon /srv/lfcs-special/foundation/index.html | awk -F: '{print $3}')
    process=$(ps -eZ | awk '/httpd_t.*httpd/{split($1,c,":"); print c[3]; exit}')
    printf '%s\n%s\n%s\n%s\n%s\n' "$(getenforce)" "$(sestatus | awk -F: '/Loaded policy name/{gsub(/ /,"",$2);print $2}')" "$current" "$expected" "$process" >/tmp/lfcs-selinux-foundation
    ;;
  selinux-02)
    semanage fcontext -a -t httpd_sys_content_t '/srv/lfcs-special/context-site(/.*)?'
    restorecon -RF /srv/lfcs-special/context-site
    systemctl restart httpd
    ;;
  selinux-03)
    semanage port -a -t http_port_t -p tcp 8124
    systemctl enable --now httpd
    ;;
  selinux-04)
    printf 'httpd_t\nuser_home_t\nread\n' >/tmp/lfcs-avc-diagnosis
    semanage fcontext -a -t httpd_sys_content_t '/srv/lfcs-special/avc-site(/.*)?'
    restorecon -RF /srv/lfcs-special/avc-site
    systemctl restart httpd
    ;;
  selinux-05)
    setsebool -P httpd_can_network_connect on
    systemctl enable --now httpd lfcs-special-backend
    ;;
  selinux-06)
    semanage fcontext -a -t httpd_sys_content_t '/srv/lfcs-special/transfer-site(/.*)?'
    restorecon -RF /srv/lfcs-special/transfer-site
    systemctl restart httpd
    ;;
  ldap-01)
    provider=$(sssctl domain-list | head -1 | sed 's/^lfcs$/ldap/')
    printf '%s\n%s\n%s\n%s\n%s\n%s\n' \
      "$(getent passwd root | cut -d: -f3)" \
      "$(getent passwd student | cut -d: -f3)" \
      "$(getent passwd directoryuser | cut -d: -f3)" \
      "$(getent passwd directoryuser | cut -d: -f4)" \
      "$(getent group ldapops | cut -d: -f3)" "$provider" >/tmp/lfcs-ldap-foundation
    ;;
  ldap-02) configure_sssd ;;
  ldap-03) configure_sssd ;;
  ldap-04)
    systemctl enable --now dirsrv@lfcs.service
    sss_cache -E || true
    systemctl restart sssd
    ;;
  ldap-05)
    sed -i 's/^auth_provider = deny$/auth_provider = ldap/' /etc/sssd/sssd.conf
    systemctl restart sssd
    ;;
  *) echo "unknown scenario: $sid" >&2; exit 2 ;;
esac
