#!/usr/bin/env bash
set -euo pipefail
# Weekly root cron; validate both downloads before touching the active configuration.
if [[ $# -gt 1 || ( $# -eq 1 && $1 != --bootstrap ) ]]; then
    echo "Usage: sudo bash update-cloudflare-ips.sh [--bootstrap]"
    echo "--bootstrap: update/persist firewall before Caddy's first start; skip Caddy reload."
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
exec 8>/run/lock/powerk-cf-update.lock
flock -n 8 || exit 0
bootstrap=false
[[ ${1:-} == --bootstrap ]] && bootstrap=true
if ! $bootstrap && [[ -z $(compose ps --status running -q caddy) ]]; then
    echo "Caddy is not running; use --bootstrap only before its first start." >&2; exit 1
fi
work="$(mktemp -d)"
changed=false
complete=false
cleanup() {
    result=$?
    trap - EXIT
    if $changed && ! $complete; then
        echo "Update failed; restoring previous ranges and firewall." >&2
        cat "$work/previous" > "$DEPLOY_DIR/cloudflare-ips.caddy"
        bash "$DEPLOY_DIR/scripts/firewall.sh" || echo "ERROR: firewall rollback failed; inspect immediately" >&2
        if ! $bootstrap; then
            compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile || echo "ERROR: Caddy rollback failed" >&2
        fi
    fi
    rm -rf -- "$work"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
for family in v4 v6; do
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 10 --max-time 60 --retry 3 \
        "https://www.cloudflare.com/ips-$family" -o "$work/$family"
done
python3 "$DEPLOY_DIR/scripts/cloudflare-ranges.py" generate "$work/v4" "$work/v6" > "$work/candidate"
cp "$DEPLOY_DIR/cloudflare-ips.caddy" "$work/previous"
changed=true
# Keep the inode: Caddy has a read-only FILE bind mount. Atomic rename would leave it stale.
# The cron lock prevents concurrent updates; Caddy keeps serving its in-memory config.
cat "$work/candidate" > "$DEPLOY_DIR/cloudflare-ips.caddy"
if ! $bootstrap; then
    compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
fi
bash "$DEPLOY_DIR/scripts/firewall.sh"
if ! $bootstrap; then
    compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
fi
complete=true
echo "Cloudflare ranges updated, firewall persisted, Caddy configuration applied."
