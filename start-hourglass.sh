#!/usr/bin/env bash
# Launch only the local benchmark UI. Existing model server settings are untouched.
# HOURGLASS_PORT=9000 ./start-hourglassbench.sh selects an explicit port.
set -euo pipefail
cd "$(dirname "$0")"
export NODE_ID="${NODE_ID:-$(hostname -s)}"
if [ ! -f models.json ]; then
  cp models.example.json models.json
  echo "Created models.json from the example. Configure your endpoint in Model settings."
fi
exec python3 launch.py "$@"
