#!/usr/bin/env bash
set -euo pipefail
# Own-chain updates are atomic per address family. Never flush INPUT/FORWARD.
if [[ $# -ne 0 ]]; then
    echo "Usage: sudo bash firewall.sh"
    echo "Optional PUBLIC_INTERFACE / PUBLIC_INTERFACE_V6 override default-route interfaces."
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
for command in python3 ip iptables ip6tables iptables-restore ip6tables-restore netfilter-persistent flock; do
    command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
exec 9>/run/lock/powerk-firewall.lock
flock 9
# Validate BOTH families before changing either ruleset. No shell evaluation of downloads.
ranges="$(python3 "$DEPLOY_DIR/scripts/cloudflare-ranges.py" dump "$DEPLOY_DIR/cloudflare-ips.caddy")"
interface4="${PUBLIC_INTERFACE:-$(ip -4 route show default | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}')}"
interface6="${PUBLIC_INTERFACE_V6:-$(ip -6 route show default | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}')}"
interface6="${interface6:-$interface4}"
for interface in "$interface4" "$interface6"; do
    [[ $interface =~ ^[a-zA-Z0-9_.:-]+$ ]] || { echo "Cannot determine public interface" >&2; exit 1; }
    ip link show dev "$interface" >/dev/null
done
# Docker must be installed/running before bootstrap; do not emulate its IPv4 plumbing.
iptables -w -S DOCKER-USER >/dev/null
for family in 4 6; do
    if [[ $family == 4 ]]; then
        table=iptables; restore=iptables-restore; interface=$interface4
    else
        table=ip6tables; restore=ip6tables-restore; interface=$interface6
    fi
    # IPv6 may use docker-proxy + INPUT without an IPv6 bridge. Protect both paths.
    if ! "$table" -w -S DOCKER-USER >/dev/null 2>&1; then "$table" -w -N DOCKER-USER; fi
    # Count our existing hooks before constructing the atomic restore transaction.
    input_hooks="$("$table" -w -S INPUT | awk '$0=="-A INPUT -j POWERK-HOST" {n++} END {print n+0}')"
    docker_hooks="$("$table" -w -S DOCKER-USER | awk '$0=="-A DOCKER-USER -j POWERK-CF" {n++} END {print n+0}')"
    forward_hook=false
    if "$table" -w -C FORWARD -j DOCKER-USER 2>/dev/null; then forward_hook=true; fi
    {
        echo '*filter'
        echo ':POWERK-CF - [0:0]'
        echo ':POWERK-HOST - [0:0]'
        echo '-F POWERK-CF'
        echo '-F POWERK-HOST'
        echo '-A POWERK-HOST -p tcp --dport 22 -j ACCEPT'
        echo '-A POWERK-HOST -p tcp --dport 10086 -j ACCEPT'
        while read -r version cidr; do
            [[ $version == "$family" ]] || continue
            echo "-A POWERK-HOST -p tcp -s $cidr --dport 443 -j ACCEPT"
            echo "-A POWERK-CF -i $interface -p tcp -s $cidr -m conntrack --ctorigdstport 443 --ctdir ORIGINAL -j ACCEPT"
        done <<< "$ranges"
        echo '-A POWERK-HOST -p tcp --dport 443 -j DROP'
        echo '-A POWERK-HOST -j RETURN'
        # Check original destination: Docker DNAT has already rewritten the packet.
        echo "-A POWERK-CF -i $interface -p tcp -m conntrack --ctorigdstport 443 --ctdir ORIGINAL -j DROP"
        echo "-A POWERK-CF -i $interface -p tcp -m conntrack --ctorigdstport 10086 --ctdir ORIGINAL -j ACCEPT"
        echo '-A POWERK-CF -j RETURN'
        # Refresh hooks in the SAME transaction: no unfiltered gap during cron runs.
        for ((i=0; i<input_hooks; i++)); do echo '-D INPUT -j POWERK-HOST'; done
        echo '-I INPUT 1 -j POWERK-HOST'
        for ((i=0; i<docker_hooks; i++)); do echo '-D DOCKER-USER -j POWERK-CF'; done
        echo '-I DOCKER-USER 1 -j POWERK-CF'
        if ! $forward_hook; then echo '-I FORWARD 1 -j DOCKER-USER'; fi
        echo COMMIT
    } | "$restore" --wait 10 --noflush
done
netfilter-persistent save
echo "Cloudflare-only 443 installed for IPv4/IPv6; 22 and 10086 remain open."
