#!/usr/bin/env bash
# Run from Terminal; keep that Terminal open while using Hourglass.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 launch.py "$@"
