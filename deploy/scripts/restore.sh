#!/usr/bin/env bash
set -euo pipefail
# Restore intentionally leaves services stopped on failure for operator inspection.
if [[ $# -ne 1 || ${1:-} == --help ]]; then
    echo "Usage: sudo bash restore.sh SNAPSHOT_DIRECTORY_NAME"
    echo "Stops powerk and backup; saves current data first; restores and starts both."
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $1 != */* && $1 != .* && -f "$DEPLOY_DIR/backups/$1/powerk.db" && -f "$DEPLOY_DIR/backups/$1/powerk.json" ]] || {
    echo "Snapshot not found or invalid name: $1" >&2; exit 2;
}
compose stop powerk backup
compose run --rm --no-deps backup restore "$1"
compose up -d powerk backup
