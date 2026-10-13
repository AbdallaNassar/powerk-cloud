#!/usr/bin/env bash
set -euo pipefail
# Online backup: powerk may remain running; helper serializes with daily backups.
if [[ $# -ne 0 ]]; then
    echo "Usage: sudo bash backup-now.sh  (writes deploy/backups; keeps last 14)"
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
compose run --rm --no-deps backup once
