_lfcs_complete() {
  local root kind values
  root=${LFCS_ROOT:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}
  if (( COMP_CWORD == 1 )); then
    kind=commands
  else
    case "${COMP_WORDS[1]}" in
      lab|grade|reset|solution|hint) kind=scenarios ;;
      shell) kind=hosts ;;
      mini|mini-grade|mini-reset) kind=minis ;;
      mock|mock-grade|mock-reset) kind=mocks ;;
      list) values='1 2 3 4 5 operations networking storage commands users special' ;;
      start|stop) values='lfcs-special' ;;
      *) return ;;
    esac
  fi
  if [[ -n ${kind:-} ]]; then values=$("$root/bin/lfcs" _complete "$kind" 2>/dev/null); fi
  COMPREPLY=( $(compgen -W "$values" -- "${COMP_WORDS[COMP_CWORD]}") )
}
complete -F _lfcs_complete lfcs ./bin/lfcs
