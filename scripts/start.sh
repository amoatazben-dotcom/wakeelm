#!/usr/bin/env sh
set -eu
exec uvicorn app.main:create_app --factory --host "${APP_HOST:-0.0.0.0}" --port "${PORT:-${APP_PORT:-8000}}" --no-access-log
