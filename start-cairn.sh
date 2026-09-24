#!/usr/bin/env bash
set -euo pipefail
CAIRN_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$CAIRN_PROJECT_DIR/cairn-terminal" start "$@"
