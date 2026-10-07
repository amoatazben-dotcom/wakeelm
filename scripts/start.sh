#!/usr/bin/env sh
set -eu
# Railway mounts volumes as root. Prepare the private directory, then drop privileges.
if [ "$(id -u)" = 0 ]; then
  workspace_root="${WORKSPACE_STORAGE_ROOT:-/data/workspaces}"
  mkdir -p "$workspace_root"
  chown agent:agent "$workspace_root"
  chmod 700 "$workspace_root"
  exec runuser -u agent -- sh "$0"
fi
# Docker-local builds carry BUILD_GIT_SHA; linked Railway builds provide the Git ref.
if [ "${BUILD_GIT_SHA:-unknown}" = unknown ]; then
  export BUILD_GIT_SHA="${RAILWAY_GIT_COMMIT_SHA:-unknown}"
fi
exec uvicorn app.main:create_app --factory --host "${APP_HOST:-0.0.0.0}" --port "${PORT:-${APP_PORT:-8000}}" --no-access-log


