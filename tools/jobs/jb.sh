




































# The repo: $SBK if set, else wherever this file sits (tools/jobs/ -> two levels up).
_JB_HERE="${BASH_SOURCE[0]:-$0}"
_JB_SBK="${SBK:-$(cd "$(dirname "$_JB_HERE")/../.." 2>/dev/null && pwd)}"
_JB_REC="$_JB_SBK/tools/jobs/jb-record.py"
_JB_DIR="${SBK_DATA_ROOT:-$HOME/.sbk-data}/jobs"
_JB_JOB=""
_JB_DONE=0
_JB_T0=0






_JB_MANO=""



[[ ( -n "${TERM:-}" && "${TERM}" != "dumb" ) || -n "${SSH_TTY:-}" ]] && _JB_MANO="[manuale]"


_jb_python() {
  for p in "$_JB_SBK/.venv/bin/python3" /opt/homebrew/bin/python3 /usr/bin/python3 python3; do
    [[ -x "$p" ]] && { echo "$p"; return 0; }
    command -v "$p" >/dev/null 2>&1 && { command -v "$p"; return 0; }
  done
  return 1
}



_jb_raw() {
  local job="$1" phase="$2" outcome="$3" detail="$4"
  mkdir -p "$_JB_DIR" 2>/dev/null || return 0
  local at file esc
  at="$(date +%Y-%m-%dT%H:%M:%S%z)"
  at="${at:0:22}:${at:22:2}"                       # +HHMM -> +HH:MM
  file="$_JB_DIR/events-$(date +%Y%m).jsonl"
  esc="${detail//\\/\\\\}"; esc="${esc//\"/\\\"}"; esc="${esc//$'\n'/ }"
  printf '{"job":"%s","phase":"%s","at":"%s","outcome":%s,"detail":"%s","expected_at":null,"host":"%s","pid":%s,"via":"bash-fallback"}\n' \
    "$job" "$phase" "$at" \
    "$([[ -n "$outcome" ]] && printf '"%s"' "$outcome" || printf 'null')" \
    "${esc:0:400}" "$(hostname -s 2>/dev/null || echo '?')" "$$" >> "$file" 2>/dev/null || true
}

_jb_call() {
  local phase="$1" job="$2" outcome="${3:-}" detail="${4:-}"
  [[ -n "$_JB_MANO" ]] && detail="${detail:+$detail }$_JB_MANO"
  local py
  if [[ -f "$_JB_REC" ]] && py="$(_jb_python)"; then
    if [[ "$phase" == "end" ]]; then
      "$py" "$_JB_REC" end "$job" --outcome "$outcome" --detail "$detail" >/dev/null 2>&1 && return 0
    else
      "$py" "$_JB_REC" start "$job" --detail "$detail" >/dev/null 2>&1 && return 0
    fi
  fi
  _jb_raw "$job" "$phase" "$outcome" "$detail"
}

jb_start() {
  _JB_JOB="$1"; _JB_DONE=0
  _JB_T0="$(date +%s)"
  _jb_call start "$_JB_JOB"
  trap '_jb_trap $?' EXIT
}


jb_done() {
  [[ -n "$_JB_JOB" ]] || return 0
  _JB_DONE=1
  _jb_call end "$_JB_JOB" "$1" "${2:-}"
}
















_JB_STOPPED_CODES="129 130 143"

_jb_signame() {
  case "$1" in
    1) echo SIGHUP ;; 2) echo SIGINT ;; 15) echo SIGTERM ;; 4) echo SIGILL ;; 6) echo SIGABRT ;;
    8) echo SIGFPE ;; 9) echo SIGKILL ;; 10) echo SIGBUS ;; 11) echo SIGSEGV ;; *) echo "signal $1" ;;
  esac
}

_jb_trap() {
  local code="${1:-0}"
  [[ -n "$_JB_JOB" && "$_JB_DONE" -eq 0 ]] || return 0
  _JB_DONE=1
  if [[ " $_JB_STOPPED_CODES " == *" $code "* ]]; then
    local sig name why="" note="$_JB_DIR/stop-$_JB_JOB.txt" m
    sig=$((code - 128)); name="$(_jb_signame "$sig")"



    if [[ -f "$note" ]]; then
      m="$(stat -f %m "$note" 2>/dev/null || echo 0)"
      if [[ "$m" -ge "${_JB_T0:-0}" ]]; then
        why="$(tr '\n' ' ' < "$note" 2>/dev/null | cut -c1-300)"
      fi
    fi
    if [[ -n "$why" ]]; then
      _jb_call end "$_JB_JOB" skipped "stopped by $name: $why"
    else
      _jb_call end "$_JB_JOB" skipped \
        "stopped by $name (by hand, launchctl, logout or shutdown): not done, the next slot catches up"
    fi
  elif [[ "$code" -gt 128 ]]; then
    _jb_call end "$_JB_JOB" failed \
      "killed by $(_jb_signame $((code - 128))) (crash; SIGKILL is often memory) (code $code)"
  else
    _jb_call end "$_JB_JOB" failed "exited without declaring an outcome (code $code)"
  fi
}
