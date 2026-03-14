#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_ROOT="$REPO_ROOT/webnovel-writer"
PYTHON_RUNNER="$SCRIPT_DIR/py"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/dashboard-service.sh start <project-root-or-workspace> [host] [port]
  ./scripts/dashboard-service.sh stop <project-root-or-workspace> [port]
  ./scripts/dashboard-service.sh status <project-root-or-workspace> [port]
  ./scripts/dashboard-service.sh restart <project-root-or-workspace> [host] [port]

Environment:
  WEBNOVEL_DASHBOARD_HOST  Default host when omitted (default: 0.0.0.0)
  WEBNOVEL_DASHBOARD_PORT  Default port when omitted (default: 5678)
EOF
}

resolve_project_root() {
  local raw_root="$1"
  "$PYTHON_RUNNER" "$APP_ROOT/scripts/webnovel.py" --project-root "$raw_root" where
}

pid_file_for() {
  local project_root="$1"
  local port="$2"
  printf '%s\n' "$project_root/.webnovel/dashboard-${port}.pid"
}

log_file_for() {
  local project_root="$1"
  local port="$2"
  printf '%s\n' "$project_root/.webnovel/dashboard-${port}.log"
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    tr -d '[:space:]' <"$pid_file"
  fi
}

is_running() {
  local pid_file="$1"
  local pid
  pid="$(read_pid "$pid_file")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

wait_for_exit() {
  local pid="$1"
  local tries=20
  while (( tries > 0 )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
    tries=$((tries - 1))
  done
  return 1
}

port_in_use() {
  local port="$1"
  python3 - <<PY
import socket
s = socket.socket()
s.settimeout(0.5)
try:
    s.bind(("0.0.0.0", int(${port})))
except OSError:
    raise SystemExit(0)
finally:
    try:
        s.close()
    except Exception:
        pass
raise SystemExit(1)
PY
}

start_dashboard() {
  local raw_root="$1"
  local host="$2"
  local port="$3"
  local project_root pid_file log_file pid

  project_root="$(resolve_project_root "$raw_root")"
  pid_file="$(pid_file_for "$project_root" "$port")"
  log_file="$(log_file_for "$project_root" "$port")"

  mkdir -p "$(dirname "$pid_file")"

  if is_running "$pid_file"; then
    pid="$(read_pid "$pid_file")"
    echo "Dashboard already running"
    echo "PID: $pid"
    echo "URL: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$port"
    echo "LOG: $log_file"
    return 0
  fi

  if port_in_use "$port"; then
    echo "ERROR: Port $port is already in use." >&2
    echo "Stop the existing listener first, or use a different port." >&2
    return 1
  fi

  (
    cd "$APP_ROOT"
    nohup env \
      WEBNOVEL_DASHBOARD_HOST="$host" \
      WEBNOVEL_DASHBOARD_PORT="$port" \
      "$PYTHON_RUNNER" -m dashboard.server \
      --project-root "$project_root" \
      --no-browser \
      >"$log_file" 2>&1 &
    echo $! >"$pid_file"
  )

  pid="$(read_pid "$pid_file")"
  sleep 1

  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    echo "ERROR: Dashboard failed to start." >&2
    [[ -f "$log_file" ]] && sed -n '1,80p' "$log_file" >&2
    return 1
  fi

  echo "Dashboard started"
  echo "PID: $pid"
  echo "URL: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$port"
  echo "LOG: $log_file"
}

stop_dashboard() {
  local raw_root="$1"
  local port="$2"
  local project_root pid_file pid

  project_root="$(resolve_project_root "$raw_root")"
  pid_file="$(pid_file_for "$project_root" "$port")"
  pid="$(read_pid "$pid_file")"

  if [[ -z "$pid" ]]; then
    echo "Dashboard is not running"
    return 0
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "Dashboard is not running"
    return 0
  fi

  kill "$pid" 2>/dev/null || true
  if ! wait_for_exit "$pid"; then
    kill -9 "$pid" 2>/dev/null || true
  fi

  rm -f "$pid_file"
  echo "Dashboard stopped"
}

status_dashboard() {
  local raw_root="$1"
  local port="$2"
  local project_root pid_file log_file pid

  project_root="$(resolve_project_root "$raw_root")"
  pid_file="$(pid_file_for "$project_root" "$port")"
  log_file="$(log_file_for "$project_root" "$port")"
  pid="$(read_pid "$pid_file")"

  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "Dashboard running"
    echo "PID: $pid"
    echo "URL: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$port"
    echo "LOG: $log_file"
    return 0
  fi

  echo "Dashboard not running"
  [[ -f "$log_file" ]] && echo "Last log: $log_file"
  return 1
}

main() {
  local action="${1:-}"
  local raw_root="${2:-}"
  local default_host="${WEBNOVEL_DASHBOARD_HOST:-0.0.0.0}"
  local default_port="${WEBNOVEL_DASHBOARD_PORT:-5678}"

  if [[ -z "$action" ]] || [[ "$action" == "-h" ]] || [[ "$action" == "--help" ]]; then
    usage
    exit 0
  fi

  if [[ -z "$raw_root" ]]; then
    usage >&2
    exit 1
  fi

  case "$action" in
    start)
      start_dashboard "$raw_root" "${3:-$default_host}" "${4:-$default_port}"
      ;;
    stop)
      stop_dashboard "$raw_root" "${3:-$default_port}"
      ;;
    status)
      status_dashboard "$raw_root" "${3:-$default_port}"
      ;;
    restart)
      stop_dashboard "$raw_root" "${4:-$default_port}" || true
      start_dashboard "$raw_root" "${3:-$default_host}" "${4:-$default_port}"
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
