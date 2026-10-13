#!/usr/bin/env bash
set -euo pipefail
# Shared helpers. Usage: source this file from another deploy/scripts script.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    echo "Usage: source common.sh  (shared helpers; use the other scripts for operations)"
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
DEPLOY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
compose() { docker compose --project-directory "$DEPLOY_DIR" -f "$DEPLOY_DIR/docker-compose.yml" "$@"; }
require_root() { if [[ $EUID -ne 0 ]]; then echo "Run this script as root (sudo bash ...)." >&2; exit 1; fi; }
