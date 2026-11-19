#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)

commands=$("$ROOT/bin/lfcs" _complete commands)
for word in start stop shell list lab grade reset solution mini mini-grade mock mock-grade progress weaknesses reset-all help hosts; do
  grep -qw "$word" <<<"$commands"
done
if grep -qw _complete <<<"$commands"; then exit 1; fi

scenarios=$("$ROOT/bin/lfcs" _complete scenarios)
grep -qw selinux-06 <<<"$scenarios"
grep -qw ldap-05 <<<"$scenarios"
if grep -qw selinux-deleted <<<"$scenarios"; then exit 1; fi
test "$(wc -w <<<"$scenarios" | tr -d ' ')" = "$("$ROOT/bin/lfcs" list | tail -1 | awk '{print $1}')"

test "$("$ROOT/bin/lfcs" _complete hosts)" = "lfcs-rc-ubuntu lfcs-rc-fedora node1 node2 node3 router1"
test "$("$ROOT/bin/lfcs" _complete minis)" = "1 2 3 4 5"
test "$("$ROOT/bin/lfcs" _complete mocks)" = "1 2 3 4 5 6"

bash_result=$(LFCS_ROOT="$ROOT" bash -c '
  source "$LFCS_ROOT/completions/lfcs.bash"
  COMP_WORDS=(./bin/lfcs lab selinux-0); COMP_CWORD=2
  _lfcs_complete
  printf "%s\n" "${COMPREPLY[@]}"
')
grep -qx selinux-01 <<<"$bash_result"
grep -qx selinux-06 <<<"$bash_result"

zsh_result=$(LFCS_ROOT="$ROOT" zsh -fc '
  fpath=("$LFCS_ROOT/completions" $fpath)
  autoload -Uz _lfcs; autoload +X _lfcs
  _describe() { local array_name=$2; eval "print -rl -- \${${array_name}[@]}"; }
  words=(./bin/lfcs lab selinux-0); CURRENT=3
  _lfcs
')
grep -qx selinux-01 <<<"$zsh_result"
grep -qx selinux-06 <<<"$zsh_result"

echo "completion checks passed: commands scenarios hosts minis mocks zsh bash"
