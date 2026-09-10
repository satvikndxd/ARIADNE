#!/usr/bin/env bash
# Dev helper: restart the API server (sandbox has no pkill).
for p in $(ls /proc | grep -E '^[0-9]+$'); do
  cmd=$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null || true)
  case "$cmd" in
    python3\ -m\ uvicorn*) kill "$p" 2>/dev/null ;;
  esac
done
sleep 1
cd "$(dirname "$0")/../apps/api" || exit 1
nohup python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT:-8000}" > /tmp/api.log 2>&1 &
sleep 5
echo "api restarted (pid $!)"
