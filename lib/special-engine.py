#!/usr/bin/env python3
"""Setup, grade, and exact reset ownership for lfcs-special scenarios."""
import os, pathlib, re, subprocess, sys, time

MODE = sys.argv[1] if len(sys.argv) > 1 else ""
SID = sys.argv[2] if len(sys.argv) > 2 else ""
if not pathlib.Path('/usr/local/lib/lfcs/verify-guest.py').is_file() or subprocess.run(['/usr/local/lib/lfcs/verify-guest.py'], capture_output=True).returncode:
    raise SystemExit('LFCS special engine: candidate guest marker missing')
SPECIAL_IDS = {f"selinux-{n:02d}" for n in range(1, 7)} | {f"ldap-{n:02d}" for n in range(1, 6)}
if MODE in {'setup', 'grade', 'reset'} and SID not in SPECIAL_IDS:
    raise SystemExit('LFCS special engine: unknown scenario ID')
FAILURES = 0

def run(command, check=True, capture=False, input=None):
    return subprocess.run(["bash", "-lc", command], check=check, text=True, input=input,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)

def ok(command):
    return run(command, check=False, capture=True).returncode == 0

def emit(command, message):
    global FAILURES
    passed = ok(command)
    if not passed: FAILURES += 1
    print(("PASS" if passed else "FAIL") + "|" + message)

def write(path, content, mode=0o644):
    p = pathlib.Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content); os.chmod(p, mode)

def sssd_config(base="dc=lfcs,dc=internal", auth="ldap"):
    write("/etc/sssd/sssd.conf", f"""[sssd]
services = nss, pam
domains = lfcs

[domain/lfcs]
id_provider = ldap
auth_provider = {auth}
ldap_uri = ldap://127.0.0.1
ldap_search_base = {base}
ldap_schema = rfc2307
ldap_id_use_start_tls = false
ldap_tls_reqcert = never
cache_credentials = false
enumerate = false
""", 0o600)
    run("systemctl enable --now sssd; sss_cache -E || true")

def httpd_conf(root, port=80, proxy=False):
    listen = "" if port == 80 else f"Listen {port}\n"
    if proxy:
        body = f"""{listen}
<VirtualHost 127.0.0.1:{port}>
  ProxyPreserveHost On
  ProxyPass / http://127.0.0.1:9005/
  ProxyPassReverse / http://127.0.0.1:9005/
</VirtualHost>
"""
    else:
        body = f"""{listen}
<VirtualHost 127.0.0.1:{port}>
  DocumentRoot \"{root}\"
  <Directory \"{root}\">
    Require all granted
  </Directory>
</VirtualHost>
"""
    write("/etc/httpd/conf.d/99-lfcs-special.conf", body)

def reset():
    run("setenforce 1", check=False)
    run("systemctl disable --now httpd sssd lfcs-special-backend.service >/dev/null 2>&1 || true", check=False)
    run("rm -f /etc/httpd/conf.d/99-lfcs-special.conf /etc/sssd/sssd.conf /etc/systemd/system/lfcs-special-backend.service /usr/local/lib/lfcs/special-backend.py", check=False)
    run("chown root:sssd /etc/sssd; chmod 0750 /etc/sssd", check=False)
    run("systemctl daemon-reload; systemctl reset-failed httpd sssd lfcs-special-backend.service 2>/dev/null || true", check=False)
    for path in ("/srv/lfcs-special/foundation", "/srv/lfcs-special/context-site", "/srv/lfcs-special/avc-site", "/srv/lfcs-special/transfer-site"):
        run(f"semanage fcontext -d '{path}(/.*)?' 2>/dev/null || true", check=False)
    run("semanage port -d -t http_port_t -p tcp 8124 2>/dev/null || true", check=False)
    run("setsebool -P httpd_can_network_connect off", check=False)
    run("rm -rf /srv/lfcs-special/foundation /srv/lfcs-special/context-site /srv/lfcs-special/avc-site /srv/lfcs-special/transfer-site", check=False)
    run("rm -f /tmp/lfcs-selinux-foundation /tmp/lfcs-avc-diagnosis /tmp/lfcs-ldap-foundation", check=False)
    run("sss_cache -E >/dev/null 2>&1 || true; rm -rf /var/lib/sss/db/* /var/lib/sss/mc/*", check=False)
    run("systemctl enable --now dirsrv@lfcs.service oddjobd.service", check=False)

def setup():
    reset()
    if SID == "selinux-01":
        run("install -d -m 0755 /srv/lfcs-special/foundation; echo foundation-ready >/srv/lfcs-special/foundation/index.html; semanage fcontext -a -t httpd_sys_content_t '/srv/lfcs-special/foundation(/.*)?'; restorecon -RF /srv/lfcs-special/foundation")
        httpd_conf("/srv/lfcs-special/foundation")
        run("systemctl enable --now httpd")
    elif SID in {"selinux-02", "selinux-04", "selinux-06"}:
        path = {"selinux-02":"context-site", "selinux-04":"avc-site", "selinux-06":"transfer-site"}[SID]
        text = {"selinux-02":"context-ready", "selinux-04":"avc-ready", "selinux-06":"transfer-ready"}[SID]
        full = f"/srv/lfcs-special/{path}"
        bad_type = "user_home_t" if SID == "selinux-04" else "var_t"
        run(f"install -d -m 0755 {full}; echo {text} >{full}/index.html; chown -R root:root {full}; chmod -R a+rX {full}; chcon -R -t {bad_type} {full}")
        httpd_conf(full)
        run("systemctl enable --now httpd; curl -fsS http://127.0.0.1/ >/dev/null || true")
    elif SID == "selinux-03":
        run("install -d -m 0755 /var/www/html; echo port-ready >/var/www/html/index.html; restorecon -RF /var/www/html")
        httpd_conf("/var/www/html", 8124)
        run("systemctl enable httpd; systemctl start httpd || true")
    elif SID == "selinux-05":
        write("/usr/local/lib/lfcs/special-backend.py", "from http.server import BaseHTTPRequestHandler,HTTPServer\nclass H(BaseHTTPRequestHandler):\n def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b'boolean-ready\\n')\n def log_message(self,*a): pass\nHTTPServer(('127.0.0.1',9005),H).serve_forever()\n", 0o755)
        write("/etc/systemd/system/lfcs-special-backend.service", "[Unit]\nDescription=LFCS special backend\n[Service]\nExecStart=/usr/bin/python3 /usr/local/lib/lfcs/special-backend.py\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\n")
        httpd_conf("", proxy=True)
        run("systemctl daemon-reload; systemctl enable --now lfcs-special-backend httpd; curl -fsS http://127.0.0.1/ >/dev/null || true")
    elif SID == "ldap-01":
        sssd_config()
    elif SID == "ldap-02":
        pass
    elif SID == "ldap-03":
        sssd_config("dc=wrong,dc=internal")
    elif SID == "ldap-04":
        sssd_config(); run("systemctl stop dirsrv@lfcs.service; sss_cache -E || true")
    elif SID == "ldap-05":
        sssd_config(auth="deny")
    else:
        raise SystemExit(f"unknown special scenario: {SID}")

def grade():
    emit("test \"$(getenforce)\" = Enforcing", "SELinux remains enforcing")
    if SID == "selinux-01":
        trim="sed 's/^[[:space:]]*//; s/[[:space:]]*$//'"
        emit(f"test -f /tmp/lfcs-selinux-foundation && test \"$(wc -l </tmp/lfcs-selinux-foundation)\" -eq 5 && test \"$(sed -n 1p /tmp/lfcs-selinux-foundation | {trim})\" = Enforcing && test \"$(sed -n 2p /tmp/lfcs-selinux-foundation | {trim})\" = targeted", "report records real enforcing mode and policy")
        emit(f"test \"$(sed -n 3p /tmp/lfcs-selinux-foundation | {trim})\" = httpd_sys_content_t && test \"$(sed -n 4p /tmp/lfcs-selinux-foundation | {trim})\" = httpd_sys_content_t", "report records current and expected file types")
        emit(f"test \"$(sed -n 5p /tmp/lfcs-selinux-foundation | {trim})\" = httpd_t && ps -eZ | grep -q 'httpd_t.*httpd'", "report records the real httpd process type")
    elif SID in {"selinux-02", "selinux-04", "selinux-06"}:
        path = {"selinux-02":"context-site", "selinux-04":"avc-site", "selinux-06":"transfer-site"}[SID]
        text = {"selinux-02":"context-ready", "selinux-04":"avc-ready", "selinux-06":"transfer-ready"}[SID]
        full=f"/srv/lfcs-special/{path}"
        emit(f"semanage fcontext -l | grep -F '{full}(/.*)?' | grep -q httpd_sys_content_t", "persistent file-context mapping is exact")
        emit(f"test \"$(stat -c %C {full}/index.html | cut -d: -f3)\" = httpd_sys_content_t && restorecon -RF {full} && test \"$(stat -c %C {full}/index.html | cut -d: -f3)\" = httpd_sys_content_t", "actual context is correct and survives restorecon")
        emit(f"systemctl restart httpd && curl -fsS http://127.0.0.1/ | grep -qx {text}", "httpd serves the required content after restart")
        if SID == "selinux-04":
            emit("test \"$(sed -n 1p /tmp/lfcs-avc-diagnosis)\" = httpd_t && test \"$(sed -n 2p /tmp/lfcs-avc-diagnosis)\" = user_home_t && test \"$(sed -n 3p /tmp/lfcs-avc-diagnosis)\" = read", "AVC diagnosis identifies source, target, and permission")
    elif SID == "selinux-03":
        emit("semanage port -l | awk '$1==\"http_port_t\" && $2==\"tcp\" {for(i=3;i<=NF;i++) if($i==\"8124\" || $i ~ /(^|,)8124(,|$)/) found=1} END{exit !found}'", "TCP 8124 has the persistent web-port label")
        emit("systemctl is-active --quiet httpd && systemctl is-enabled --quiet httpd", "httpd is active and enabled")
        emit("ss -lntH 'sport = :8124' | grep -q . && curl -fsS http://127.0.0.1:8124/ | grep -qx port-ready", "non-standard listener serves the endpoint")
    elif SID == "selinux-05":
        emit("test \"$(getsebool httpd_can_network_connect | awk '{print $3}')\" = on && semanage boolean -l | awk '$1==\"httpd_can_network_connect\" && $2==\"(on\" && $3==\",\" && $4==\"on)\" {ok=1} END{exit !ok}'", "web outbound-connect boolean is enabled persistently")
        emit("systemctl is-active --quiet httpd && systemctl is-enabled --quiet httpd && systemctl is-active --quiet lfcs-special-backend", "proxy and backend services are active")
        emit("curl -fsS http://127.0.0.1/ | grep -qx boolean-ready", "reverse proxy reaches its confined backend")
    else:
        emit("getent passwd root >/dev/null && getent passwd student >/dev/null", "local identities remain resolvable")
        emit("getent passwd directoryuser | awk -F: '$1==\"directoryuser\" && $3==22001 && $4==22001' && ! grep -q '^directoryuser:' /etc/passwd", "directory-backed user resolves through NSS")
        emit("getent group ldapops | awk -F: '$1==\"ldapops\" && $3==22001' && ! grep -q '^ldapops:' /etc/group", "directory-backed group resolves through NSS")
        emit("id directoryuser | grep -q 'uid=22001(directoryuser).*gid=22001(ldapops)'", "id resolves the LDAP identity and group")
        emit("test -f /etc/sssd/sssd.conf && test \"$(stat -c %U /etc/sssd/sssd.conf)\" = root && test $((8#$(stat -c %a /etc/sssd/sssd.conf) & 7)) -eq 0 && systemctl is-active --quiet sssd && systemctl is-enabled --quiet sssd", "SSSD configuration and lifecycle are correct")
        if SID == "ldap-01":
            emit("test \"$(sed -n 1p /tmp/lfcs-ldap-foundation)\" = 0 && test \"$(sed -n 2p /tmp/lfcs-ldap-foundation)\" = 1000 && test \"$(sed -n 3p /tmp/lfcs-ldap-foundation)\" = 22001 && test \"$(sed -n 4p /tmp/lfcs-ldap-foundation)\" = 22001 && test \"$(sed -n 5p /tmp/lfcs-ldap-foundation)\" = 22001 && test \"$(sed -n 6p /tmp/lfcs-ldap-foundation)\" = ldap", "foundation report traces local and LDAP identities")
        if SID == "ldap-04":
            emit("systemctl is-active --quiet dirsrv@lfcs.service", "LDAP provider service is restored")
        if SID == "ldap-05":
            emit("pamtester login directoryuser authenticate </var/lib/lfcs-special/credentials/directoryuser >/dev/null", "directory identity authenticates through PAM")

def health():
    emit("systemctl is-system-running | grep -Eq '^(running|degraded)$'", "systemd is healthy")
    emit("test \"$(getenforce)\" = Enforcing && sestatus | grep -q 'Loaded policy name:.*targeted'", "SELinux targeted policy is enforcing")
    emit("case $(uname -m) in aarch64|x86_64) ;; *) exit 1;; esac; . /etc/os-release && test \"$ID\" = fedora", "Fedora baseline is present")
    emit("ip -4 addr show dev eth0 | grep -q 'inet ' && ip route show default | grep -q '^default '", "management network is configured")
    emit("systemctl is-active --quiet dirsrv@lfcs.service && ldapsearch -LLL -x -H ldap://127.0.0.1 -b dc=lfcs,dc=internal uid=directoryuser uidNumber | grep -q '^uidNumber: 22001$'", "directory infrastructure is reachable")
    emit("test \"$(cat /var/lib/lfcs-special/infrastructure-sentinel)\" = lfcs-special-infrastructure-v1", "infrastructure sentinel is preserved")

if MODE == "setup": setup()
elif MODE == "grade": grade()
elif MODE == "reset": reset()
elif MODE == "reset-all": reset()
elif MODE == "health":
    health()
    if FAILURES: raise SystemExit(1)
else: raise SystemExit("usage: special-engine.py setup|grade|reset|reset-all|health SCENARIO")
