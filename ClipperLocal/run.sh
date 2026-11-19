#!/usr/bin/env bash
# Starts the desktop app (it starts the engine by itself).
cd "$(dirname "$0")"
if [ -x ./clipperlocal-app ]; then
  exec ./clipperlocal-app
else
  echo "Desktop app not built - opening the browser version instead."
  exec ./.venv/bin/python -m app.server
fi
