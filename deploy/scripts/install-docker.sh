#!/usr/bin/env bash
set -euo pipefail
# Docker's official apt repository, pinned packages for Ubuntu 22.04 x86_64.
if [[ $# -ne 0 ]]; then
    echo "Usage: sudo bash install-docker.sh"
    echo "Requires preinstalled curl, CA certificates, python3, iptables and netfilter-persistent."
    echo "Review the exact package pins below before installing; no unpinned fallback."
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_root
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 && $(dpkg --print-architecture) == amd64 ]] || {
    echo "This installer targets Ubuntu 22.04 amd64 only." >&2; exit 1;
}
for command in curl python3 iptables ip6tables netfilter-persistent flock; do
    command -v "$command" >/dev/null || { echo "Missing prerequisite: $command" >&2; exit 1; }
done
[[ -s /etc/ssl/certs/ca-certificates.crt ]] || { echo "Missing system CA certificates" >&2; exit 1; }
# Avoid implicitly removing/replacing a preexisting container installation.
for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
        echo "Conflicting package $package installed; resolve it before running this installer." >&2; exit 1
    fi
done
install -m 0755 -d /etc/apt/keyrings
key="$(mktemp)"
trap 'rm -f -- "$key"' EXIT
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 10 --max-time 60 https://download.docker.com/linux/ubuntu/gpg -o "$key"
grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$key"
install -m 0644 "$key" /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: jammy
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
# Versions installed and verified on the production VPS on 2026-10-12.
# Upgrade these together after testing; old pins are NOT a security-update strategy.
engine_version='5:29.9.0-1~ubuntu.22.04~jammy'
containerd_version='2.4.1-2~ubuntu.22.04~jammy'
buildx_version='0.38.0-1~ubuntu.22.04~jammy'
compose_version='5.6.0-1~ubuntu.22.04~jammy'
packages=("docker-ce=$engine_version" "docker-ce-cli=$engine_version"
          "containerd.io=$containerd_version" "docker-buildx-plugin=$buildx_version"
          "docker-compose-plugin=$compose_version")
apt-get update
# Fail before package installation if any exact version is unavailable.
for spec in "${packages[@]}"; do
    package=${spec%%=*}; version=${spec#*=}
    apt-cache madison "$package" | awk '{print $3}' | grep -Fx "$version" >/dev/null || {
        echo "Pinned version unavailable: $spec. Review and update pins; not falling back." >&2; exit 1;
    }
done
apt-get install -y --no-install-recommends "${packages[@]}"
systemctl enable --now docker
docker version
docker compose version
echo "Docker installed. Apply the powerk firewall before publishing containers."
