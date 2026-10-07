#!/usr/bin/env sh
set -eu
# Docker-local builds carry BUILD_GIT_SHA; linked Railway builds provide the Git ref.
if [ "${BUILD_GIT_SHA:-unknown}" = unknown ]; then
  export BUILD_GIT_SHA="${RAILWAY_GIT_COMMIT_SHA:-unknown}"
fi
exec uvicorn app.main:create_app --factory --host "${APP_HOST:-0.0.0.0}" --port "${PORT:-${APP_PORT:-8000}}" --no-access-log
