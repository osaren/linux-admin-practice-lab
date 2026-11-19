#!/usr/bin/env bash
set -euo pipefail

NODES=(node1 node2 node3 router1)
STATE=/run/lfcs-lab

[[ -x /usr/local/lib/lfcs/verify-guest.py ]] && /usr/local/lib/lfcs/verify-guest.py || {
  echo 'LFCS topology: candidate guest marker missing; refusing privileged operation' >&2; exit 1;
}

check_owned_topology() {
  local ns
  for ns in "${NODES[@]}"; do
    ip netns list | awk '{print $1}' | grep -qx "$ns" || continue
    [[ $(cat "/etc/netns/$ns/lfcs-owner" 2>/dev/null) == lfcs-release-candidate-v1 ]] || {
      echo "LFCS topology: unowned namespace $ns; preserved" >&2; return 1;
    }
  done
  if ip link show lfcs-mgmt0 >/dev/null 2>&1; then
    [[ $(cat /etc/netns/router1/lfcs-owner 2>/dev/null) == lfcs-release-candidate-v1 ]] || {
      echo 'LFCS topology: unowned management link; preserved' >&2; return 1;
    }
  fi
}

stop_services() {
  mkdir -p "$STATE"
  for file in "$STATE/node2-http.pid" "$STATE/node3-http.pid"; do
    [[ -f "$file" ]] || continue
    pid=$(cat "$file" 2>/dev/null || true)
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      case "${file##*/}" in node2-http.pid) ns=node2 ;; node3-http.pid) ns=node3 ;; *) echo "LFCS topology: unrecognized PID file $file" >&2; return 1 ;; esac
      if kill -0 "$pid" 2>/dev/null; then
        [[ $(ip netns identify "$pid" 2>/dev/null) == "$ns" && $(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null) == *'python3 -m http.server 8080'* ]] || {
          echo "LFCS topology: PID $pid is not the owned $ns server; preserved" >&2; return 1;
        }
      fi
      kill "$pid" 2>/dev/null || true
      for _ in {1..100}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.02
      done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$file"
  done
}

wait_http() {
  local ns=$1 port=$2 pid_file=$3
  for _ in {1..200}; do
    ip netns exec "$ns" curl --max-time 1 -fsS "http://127.0.0.1:${port}/" >/dev/null 2>&1 && return 0
    [[ -s $pid_file ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null || return 1
    sleep 0.05
  done
  return 1
}

destroy() {
  check_owned_topology
  stop_services
  ip link del lfcs-mgmt0 2>/dev/null || true
  for ns in "${NODES[@]}"; do
    ip netns del "$ns" 2>/dev/null || true
  done
}

pair() {
  local node=$1 subnet=$2 slot=$3
  ip link add "v-${node}" type veth peer name "v-r${slot}"
  ip link set "v-${node}" netns "$node"
  ip link set "v-r${slot}" netns router1
  ip -n "$node" link set "v-${node}" name eth0
  ip -n router1 link set "v-r${slot}" name "eth${slot}"
  ip -n "$node" addr add "10.10.${subnet}.10/24" dev eth0
  ip -n router1 addr add "10.10.${subnet}.1/24" dev "eth${slot}"
  ip -n "$node" -6 addr add "fd10:10:${subnet}::10/64" dev eth0
  ip -n router1 -6 addr add "fd10:10:${subnet}::1/64" dev "eth${slot}"
  ip -n "$node" link set eth0 up
  ip -n router1 link set "eth${slot}" up
  ip -n "$node" route add default via "10.10.${subnet}.1"
  ip -n "$node" -6 route add default via "fd10:10:${subnet}::1"
}

write_etc() {
  local ns=$1
  mkdir -p "/etc/netns/${ns}"
  printf '%s\n' lfcs-release-candidate-v1 >"/etc/netns/${ns}/lfcs-owner"
  cat >"/etc/netns/${ns}/hosts" <<EOF
127.0.0.1 localhost
127.0.1.1 lfcs
10.10.1.10 node1
10.10.2.10 node2
10.10.3.10 node3
10.10.1.1 router1
EOF
  printf 'nameserver 1.1.1.1\n' >"/etc/netns/${ns}/resolv.conf"
}

start_services() {
  mkdir -p "$STATE" /srv/lfcs/node2 /srv/lfcs/node3
  printf 'backend=node2\n' >/srv/lfcs/node2/index.html
  printf 'backend=node3\n' >/srv/lfcs/node3/index.html
  ip netns exec node2 python3 -m http.server 8080 --bind 0.0.0.0 \
    --directory /srv/lfcs/node2 >"$STATE/node2-http.log" 2>&1 &
  echo $! >"$STATE/node2-http.pid"
  ip netns exec node3 python3 -m http.server 8080 --bind 0.0.0.0 \
    --directory /srv/lfcs/node3 >"$STATE/node3-http.log" 2>&1 &
  echo $! >"$STATE/node3-http.pid"
  wait_http node2 8080 "$STATE/node2-http.pid"
  wait_http node3 8080 "$STATE/node3-http.pid"
}

reset() {
  destroy
  for ns in "${NODES[@]}"; do
    ip netns add "$ns"
    ip -n "$ns" link set lo up
    write_etc "$ns"
  done
  pair node1 1 1
  pair node2 2 2
  pair node3 3 3
  ip link add lfcs-mgmt0 type veth peer name v-r0
  ip link set v-r0 netns router1
  ip addr add 10.10.0.2/24 dev lfcs-mgmt0
  ip link set lfcs-mgmt0 up
  ip -n router1 link set v-r0 name eth0
  ip -n router1 addr add 10.10.0.1/24 dev eth0
  ip -n router1 link set eth0 up
  for subnet in 1 2 3; do ip route add "10.10.${subnet}.0/24" via 10.10.0.1; done
  ip netns exec router1 sysctl -q -w net.ipv4.ip_forward=1
  ip netns exec router1 sysctl -q -w net.ipv6.conf.all.forwarding=1
  start_services
}

case "${1:-}" in
  reset) reset ;;
  destroy) destroy ;;
  services) stop_services; start_services ;;
  *) echo "usage: topology.sh reset|destroy|services" >&2; exit 2 ;;
esac
