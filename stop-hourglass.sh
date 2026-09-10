#!/usr/bin/env bash
set -euo pipefail
exec "$(dirname "$0")/stop-hourglass-bench.sh" "$@"
