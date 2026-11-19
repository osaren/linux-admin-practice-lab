#!/usr/bin/env bash
set -euo pipefail
if [[ ! -x /usr/local/lib/lfcs/verify-guest.py ]] || ! /usr/local/lib/lfcs/verify-guest.py; then
  echo 'LFCS provisioning: candidate guest marker missing' >&2
  exit 1
fi

marker=/var/lib/lfcs-special/provisioned-v1
if test -f "$marker"; then exit 0; fi

dnf -q -y install \
  policycoreutils-python-utils setroubleshoot-server audit \
  httpd mod_proxy_html \
  sssd sssd-ldap sssd-tools openldap-clients \
  389-ds-base authselect oddjob oddjob-mkhomedir pamtester curl python3

install -d -m 0755 /var/lib/lfcs-special /srv/lfcs-special /usr/local/lib/lfcs
credentials=/var/lib/lfcs-special/credentials
install -d -o root -g root -m 0700 "$credentials"

ensure_password() (
  path=$1
  test ! -s "$path" || exit 0
  umask 077
  temporary=$(mktemp "$credentials/.password.XXXXXXXX")
  trap 'rm -f -- "$temporary"' EXIT
  python3 -c 'import secrets, sys; print(secrets.token_hex(24), end=sys.argv[1])' "$2" >"$temporary"
  ln -- "$temporary" "$path" || test -s "$path"
)

manager_password_file=$credentials/manager
learner_password_file=$credentials/directoryuser
# LDAP client tools use the file bytes. The PAM prompt expects a line.
ensure_password "$manager_password_file" ''
ensure_password "$learner_password_file" $'\n'

if ! id student >/dev/null 2>&1; then
  useradd -K SUB_UID_COUNT=0 -K SUB_GID_COUNT=0 -m -s /bin/bash student
fi
install -d -m 0750 /etc/sudoers.d
printf 'student ALL=(ALL) NOPASSWD: ALL\n' >/etc/sudoers.d/00-lfcs-student-admin
chmod 0440 /etc/sudoers.d/00-lfcs-student-admin
visudo -cf /etc/sudoers.d/00-lfcs-student-admin >/dev/null

authselect select sssd with-mkhomedir --force >/dev/null
systemctl enable --now oddjobd >/dev/null

if ! dsctl lfcs status >/dev/null 2>&1; then
  (
    umask 077
    config=$(mktemp "$credentials/.dscreate.XXXXXXXX")
    trap 'rm -f -- "$config"' EXIT
    cat >"$config" <<EOF
[general]
config_version = 2

[slapd]
instance_name = lfcs
root_password = $(cat "$manager_password_file")
port = 389
secure_port = 636
self_sign_cert = True

[backend-userroot]
suffix = dc=lfcs,dc=internal
create_suffix_entry = True
sample_entries = no
EOF
    dscreate from-file "$config"
  )
fi
systemctl enable --now dirsrv@lfcs.service >/dev/null

if ! ldapsearch -LLL -x -H ldap://127.0.0.1 -D 'cn=Directory Manager' \
    -y "$manager_password_file" -b dc=lfcs,dc=internal uid=directoryuser dn 2>/dev/null | grep -q '^dn:'; then
  ldapadd -x -H ldap://127.0.0.1 -D 'cn=Directory Manager' -y "$manager_password_file" <<EOF
dn: ou=People,dc=lfcs,dc=internal
objectClass: organizationalUnit
ou: People

dn: ou=Groups,dc=lfcs,dc=internal
objectClass: organizationalUnit
ou: Groups

dn: uid=directoryuser,ou=People,dc=lfcs,dc=internal
objectClass: top
objectClass: person
objectClass: organizationalPerson
objectClass: inetOrgPerson
objectClass: posixAccount
uid: directoryuser
cn: Directory User
sn: User
uidNumber: 22001
gidNumber: 22001
homeDirectory: /home/directoryuser
loginShell: /bin/bash
userPassword: $(cat "$learner_password_file")

dn: cn=ldapops,ou=Groups,dc=lfcs,dc=internal
objectClass: top
objectClass: posixGroup
cn: ldapops
gidNumber: 22001
memberUid: directoryuser
EOF
fi

if ! ldapsearch -LLL -x -H ldap://127.0.0.1 -D 'cn=Directory Manager' \
    -y "$manager_password_file" -b dc=lfcs,dc=internal -s base aci | \
    grep -q 'LFCS anonymous identity read'; then
  ldapmodify -x -H ldap://127.0.0.1 -D 'cn=Directory Manager' \
    -y "$manager_password_file" <<'EOF'
dn: dc=lfcs,dc=internal
changetype: modify
add: aci
aci: (targetattr != "userPassword")(version 3.0; acl "LFCS anonymous identity read"; allow (read,search,compare) userdn = "ldap:///anyone";)
EOF
fi

printf '%s\n' 'lfcs-special-infrastructure-v1' >/var/lib/lfcs-special/infrastructure-sentinel
chmod 0444 /var/lib/lfcs-special/infrastructure-sentinel
touch "$marker"

# Canonical baseline: infrastructure is up; learner-facing services and client
# configuration are absent.  The scenario engine owns everything below.
rm -f /etc/sssd/sssd.conf /etc/httpd/conf.d/99-lfcs-special.conf
rm -rf /srv/lfcs-special/foundation /srv/lfcs-special/context-site \
       /srv/lfcs-special/avc-site /srv/lfcs-special/transfer-site
systemctl disable --now sssd httpd lfcs-special-backend.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/lfcs-special-backend.service
systemctl daemon-reload
sss_cache -E >/dev/null 2>&1 || true
setenforce 1
