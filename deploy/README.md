# Deploying powerk with Docker

Tested on Ubuntu 22.04 amd64 with 1 GB RAM (Oracle Cloud free tier). The examples
use `powerk.example.com` for the domain and `203.0.113.10` for the public IPv4.
Run the commands on the VPS unless a section says otherwise. This checkout lives
at `/opt/powerk`; the existing systemd service and data remain at
`/etc/systemd/system/powerk.service` and `/home/ubuntu/powerk` for rollback.

The strip still connects directly to TCP **10086**. Cloudflare proxies the web UI
at **https://powerk.example.com** to Caddy on TCP **443**. The app's HTTP port
8080 is never published. Caddy forwards HTTP and WebSockets over a private Docker
network. A separate egress network permits outbound notifications. Port 80 and
UDP 443 are unused; HTTP redirects happen at the Cloudflare edge.

The backend uses the fixed subnet `172.30.86.0/24`; powerk is `172.30.86.2`.
Caddy's `extra_hosts` entry pins `powerk` to this backend address so sharing an
egress network cannot route proxy traffic outside the trusted subnet. Compose
prepends `--trusted-proxy 172.30.86.0/24` to `POWERK_ARGS`. For example, setting
`POWERK_ARGS=--secure-cookies` enables secure cookies while retaining that proxy flag.
If this subnet overlaps an existing host/VPN network, change the subnet, powerk's
backend address, Caddy's host entry and the flag together before deployment.

Outside this Compose file, pass `--trusted-proxy CIDR` explicitly for the immediate
proxy network (repeatable or comma separated); default is **none**. Caddy accepts
`CF-Connecting-IP` only from its configured Cloudflare ranges and sends `X-Real-IP`.
Powerk accepts that header only from a trusted TCP peer, otherwise it ignores all
forwarded client addresses. Its X-Forwarded-For fallback walks from the right to
the first untrusted hop. Use this chain for session metadata, audit logs and rate
limits; do not expose 8080 or configure `0.0.0.0/0` as trusted. The application
runner disables uvicorn's separate forwarding-header interpretation.

## Before the first deployment

1. Place the reviewed repository at `/opt/powerk`. Keep the old service/code/data
   intact. Record `sudo systemctl cat powerk` and save a copy of its unit, token,
   and launch command somewhere private. Have an Oracle console session available
   while changing firewall rules. Do not run the two servers against the same data.
2. In Cloudflare, configure:
   - DNS `A` record `powerk` -> `203.0.113.10`, **Proxied** (orange cloud).
   - SSL/TLS encryption mode **Full (strict)**.
   - **Always Use HTTPS** enabled and minimum visitor TLS **1.2**.
   - A 15-year Origin CA certificate for `powerk.example.com`, and
     **Authenticated Origin Pulls ON**. See [certificates](certs/README.md).
   - WebSockets enabled. Keep app/API responses uncached; do not add a “Cache
     Everything” rule for this hostname. Disable Pseudo IPv4's overwrite mode if
     enabled, so `CF-Connecting-IP` preserves the actual IPv6 client address.
3. In the VM's Oracle Security List / NSG, allow TCP 443 from the Cloudflare IPv4
   ranges in `cloudflare-ips.caddy` (and IPv6 ranges only if the VM uses IPv6), TCP
   10086 from everyone, and retain existing SSH 22 access. Do not open origin 80.
   Keep 7896 temporarily for rollback. Oracle rules are separate from host rules:
   the update script cannot update your Security List. Maintain both when the
   list changes. Alternatively allow Oracle TCP 443 from everyone and rely on
   the host Cloudflare filter plus required AOP; never expose 8080.
4. The host needs `curl`, trusted system CA certificates, `python3`, `iproute2`,
   `iptables`/`ip6tables`, `flock` and the existing `netfilter-persistent` setup.
   These are host prerequisites, not packages installed by this deployment.
   The Docker installer deliberately refuses missing prerequisites or conflicting
   container packages. It installs exact versions from Docker's official apt repo:

   ```bash
   cd /opt/powerk/deploy
   sudo bash scripts/install-docker.sh
   cp .env.example .env
   chmod 600 .env
   # Edit .env: set POWERK_DOMAIN and POWERK_IP; set your strip MAC or leave it empty.
   # Account-only install: POWERK_TOKEN= (empty).
   # Legacy compatibility only: generate a token with openssl rand -hex 32.
   sudo install -d -o 10001 -g 10001 -m 0700 backups
   sudo install -d -o root -g root -m 0700 certs
   ```

   Put the three certificate files in `certs/` as described there. `POWERK_DOMAIN`
   must match the certificate; Caddy serves only that hostname. Leave `POWERK_TOKEN`
   empty for account-only operation, or set it for legacy clients;
   a configured legacy token grants full strip access and bypasses account roles.
   `.env` is parsed by Compose; do not `source` it. Quote values containing `$` with
   single quotes to avoid Compose interpolation.
   `POWERK_ARGS` accepts quoted extra CLI arguments, without shell evaluation.
   The template sets `POWERK_ARGS=--secure-cookies` for HTTPS. Registration is open by default;
   add `--no-open-registration` to close it after creating the required accounts.
   `POWERK_MAC` remains an optional TCP allowlist. Leave
   `POWERK_FCM_SERVICE_ACCOUNT` empty unless the credential file is installed.
   Do not override ports or `--data`: healthcheck, proxy and volume paths are fixed.

5. Build and validate before interrupting the old service:

   ```bash
   sudo docker compose build --pull powerk
   sudo docker compose pull caddy backup
   sudo docker compose config --quiet
   sudo docker compose run --rm --no-deps powerk --help
   sudo docker compose run --rm --no-deps caddy caddy validate \
     --config /etc/caddy/Caddyfile --adapter caddyfile
   ```

   `compose config --quiet` avoids printing the token. The healthcheck accepts all
   HTTP statuses below 500 (including 401); it checks HTTP responsiveness, not
   authentication correctness, strip connectivity or TLS.

6. Refresh the bootstrap IP snapshot and install firewall rules **before** starting
   published ports. The host's existing final INPUT REJECT remains intact:

   ```bash
   sudo bash scripts/update-cloudflare-ips.sh --bootstrap
   sudo install -m 0644 systemd/powerk-firewall.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now powerk-firewall.service
   sudo iptables -S POWERK-HOST
   sudo iptables -S POWERK-CF
   sudo ip6tables -S POWERK-HOST
   sudo ip6tables -S POWERK-CF
   ```

   The script manages only `POWERK-HOST` and `POWERK-CF` plus their hooks. It allows
   22 and 10086, restricts 443 to Cloudflare, and leaves other host policy alone.
   Docker DNAT bypasses INPUT, so DOCKER-USER checks `--ctorigdstport 443` with
   `--ctdir ORIGINAL` on the public interface, before established-connection
   shortcuts. INPUT also protects IPv6 docker-proxy traffic. Default-route
   interfaces are detected automatically; for multi-homed hosts set
   `PUBLIC_INTERFACE` / `PUBLIC_INTERFACE_V6` consistently in root cron and a
   systemd service environment override. This VM is assumed to use Docker's
   iptables backend; native nftables-only Docker is not supported by these scripts.

   Rules persist through `netfilter-persistent save`. The systemd unit reapplies
   them after Docker starts/restarts. Verify both families again after a reboot
   or Docker upgrade. Do not flush Docker's chains or restore an old full ruleset
   while Docker is running. AOP is also required at TLS, including during startup.

## Move from systemd to Compose

Build, certificate validation and the firewall setup above can run while systemd
still serves the strip. The following section is the cutover window:

```bash
cd /opt/powerk/deploy
sudo systemctl stop powerk.service
sudo systemctl disable powerk.service
sudo ss -lntp | grep -E ':(10086|7896)\b' || true
# Confirm nothing is still listening on 10086 before proceeding.
sudo docker compose create powerk
volume_dir="$(sudo docker volume inspect --format '{{ .Mountpoint }}' powerk_powerk-data)"
test -n "$volume_dir"
sudo python3 - "$volume_dir" <<'PY'
import json, os, pathlib, sqlite3, sys
source = pathlib.Path('/home/ubuntu/powerk')
target = pathlib.Path(sys.argv[1])
if any(target.iterdir()):
    raise SystemExit('Volume is not empty; inspect it instead of overwriting')
raw = (source / 'powerk.json').read_bytes()
json.loads(raw)
# SQLite backup includes committed WAL records; a bare DB copy might omit them.
with sqlite3.connect((source / 'powerk.db').as_uri() + '?mode=ro', uri=True) as old:
    with sqlite3.connect(target / 'powerk.db') as new:
        old.backup(new)
        assert new.execute('PRAGMA quick_check').fetchall() == [('ok',)]
(target / 'powerk.json').write_bytes(raw)
os.chown(target, 10001, 10001)
os.chmod(target, 0o700)
for name in ('powerk.db', 'powerk.json'):
    os.chown(target / name, 10001, 10001)
    os.chmod(target / name, 0o600)
PY
# Keep a migration snapshot OUTSIDE rotating backups, for old-code rollback.
sudo tar -C "$volume_dir" -czf /home/ubuntu/powerk-before-docker.tgz powerk.json powerk.db
sudo chmod 600 /home/ubuntu/powerk-before-docker.tgz
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 powerk caddy backup
```

The app runs as UID/GID **10001**. A fresh named volume inherits `/data` ownership
from the image, but copied legacy files need the explicit ownership above. Never
run `docker compose down -v` or prune volumes. Backup files contain secrets and
account data; protect both `/data` and the host backup directory.

To assign existing strips to an account, first register the intended owner against
this data. Preserve the pre-Docker snapshot, then stop the app and run the one-time
ownership migration (replace the phone number with that registered account):

```bash
sudo docker compose stop powerk
sudo docker compose run --rm --no-deps --entrypoint python powerk \
  -m powerk migrate --data /data --owner +201001234567
sudo docker compose up -d powerk
```

The entry-point override is required because the normal container entry point
always runs `serve`. No account is created automatically. See
[server/README.md](../server/README.md) for migration and rollback semantics.

Verify from a computer outside the VM:

- `https://powerk.example.com` loads and login works. `/powerk.py` downloads
  the provisioner on the current server (later app releases may require auth).
- `http://powerk.example.com` redirects to HTTPS at Cloudflare.
- `curl --connect-timeout 5 --max-time 10 --resolve powerk.example.com:443:203.0.113.10 https://powerk.example.com/`
  fails: the public origin must not answer an ordinary Internet client.
- The strip becomes **online** and reports fresh readings; check the UI and logs.
  It reconnects to the same IP and TCP 10086 automatically, **without provisioning
  again**. Do not reset its Wi-Fi setup. Test one safe outlet action.
- App health is healthy, backup logs report success, and there is a timestamped
  directory under `backups/`. Verify the edge TLS configuration with SSL Labs.

After successful verification, remove Oracle's 7896 ingress rule and close it on
the host. Find and delete **every exact matching** legacy ACCEPT rule in both
families; existing rules may include source addresses or extra matches:

```bash
sudo iptables -S INPUT
sudo ip6tables -S INPUT
# Example ONLY if this exactly matches a listed rule (repeat for duplicates):
sudo iptables -D INPUT -p tcp --dport 7896 -j ACCEPT
# For matching IPv6 rules, use ip6tables -D with their exact arguments too.
sudo netfilter-persistent save
```

With the existing final REJECT, new connections are now blocked. To terminate
already-established legacy sessions too, insert a specific TCP 7896 REJECT before
the host's established-connection ACCEPT, then persist it. Keep SSH and 10086
rules. Check that no other published container maps 7896. Update phone/browser
settings to the HTTPS URL; older Android builds may require the later client
release to support the new authentication flow.

## Maintenance

### Optional Android push notifications (FCM)

Enable the Firebase Cloud Messaging HTTP v1 API in the app's Firebase project and
create a service-account credential authorized to send messages for that project.
The server needs `project_id`, `client_email`, and an RSA `private_key` from that JSON.
The Android `google-services.json` is a different file and is not a server credential.

Create the mounted directory and install the credential with permissions readable by
the container's UID/GID 10001:

```bash
cd /opt/powerk/deploy
sudo install -d -o 10001 -g 10001 -m 0700 secrets
sudo install -o 10001 -g 10001 -m 0400 /secure/path/service-account.json secrets/firebase-service-account.json
```

Set `POWERK_FCM_SERVICE_ACCOUNT=/secrets/firebase-service-account.json` in `.env`.
Compose passes it to the server and mounts `./secrets:/secrets:ro` only into powerk.
`deploy/secrets/` is excluded from git and the Docker build context. Keep this directory when updating the checkout;
the regular data backups do not include it. Restart powerk after credential rotation.
If FCM is not configured, **clear the value in the copied `.env.example`**:
`POWERK_FCM_SERVICE_ACCOUNT=`. Registration and all other server features still work.
A configured but unreadable/invalid file fails startup with a generic error.

The worker uses outbound HTTPS to `oauth2.googleapis.com` and `fcm.googleapis.com`
on the existing egress network. OAuth credentials are cached in memory. The API exposes
only FCM availability/device count, never credentials or device tokens. After the app
registers its device, `/api/alerts/test` tests the caller's devices alongside their
other channels. Check delivery on a real Android device before relying on production
pushes; provider acceptance alone does not prove delivery.

### WebSocket transport

Use `POWERK_ARGS=--secure-cookies` for this HTTPS deployment. Browser connections use
`wss://powerk.example.com/api/ws`; their Origin must match the original Host and
HTTPS scheme. The app does not trust arbitrary `X-Forwarded-Proto` values. Caddy
preserves Host and supplies the trusted client IP as before.

No Caddy route change is required. Its [reverse proxy supports WebSocket upgrades](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#streaming).
The current [64 KB request-body limit](https://caddyserver.com/docs/caddyfile/directives/request_body)
applies to the HTTP request body; this GET upgrade has no body and subsequent frames
use the upgraded connection. The [encode response matcher](https://caddyserver.com/docs/caddyfile/directives/encode)
targets compressible HTTP responses, not the bodyless 101 upgrade. These conclusions
follow the Caddy documentation; this checkout's tests exercise uvicorn's real upgrade,
not the production Cloudflare/Caddy path. During deployment verify a 101 response,
the initial `state` frame, and 25-second `ping` frames through the public hostname.
Caddy reloads and Cloudflare maintenance may disconnect sockets; the web UI reconnects
with jitter and keeps 2-second HTTP polling while disconnected.

The strict CSP retains `connect-src 'self'`: [CSP3's same-host/port matching](https://www.w3.org/TR/CSP3/#match-url-to-source-expression)
allows HTTP→WS and HTTPS→WSS. No wildcard connection sources or inline exceptions
are added. A browser that blocks this transport still uses authenticated polling.

From `/opt/powerk/deploy`, inspect `sudo docker compose ps` and
`sudo docker compose logs -f --tail=100 powerk caddy backup`. JSON logs rotate at
10 MB with three files per service; Caddy access logs go to stdout. Access logs
include URLs, so avoid putting tokens in query strings. Docker health status is
informational: `restart: unless-stopped` restarts exited containers, not unhealthy
ones. Monitor health, backup failures, disk space and certificate expiration.

Before updating code, take `sudo bash scripts/backup-now.sh`, preserve a copy
outside the 14-snapshot retention, and record the current release. Place the next
reviewed checkout at `/opt/powerk` while preserving `.env`, `certs/`, `backups/` and
optional `apk/`. Build and validate as above, then:

```bash
sudo docker compose up -d --build --force-recreate powerk
sudo docker compose up -d caddy backup
sudo bash scripts/firewall.sh
sudo docker compose ps
```

Build while the old container serves, then recreate for a short reconnect. Caddy
may briefly return 502 while the app starts. For Caddy config/certificate changes:

```bash
sudo docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

`Caddyfile` and `cloudflare-ips.caddy` are **file** bind mounts. The updater writes
the range file in place to preserve its inode. If an editor or checkout replaces
either file using rename, recreate Caddy (`sudo docker compose up -d --force-recreate
caddy`) to mount the new inode before validating/reloading. Certificates are a
directory mount, so replacing files within it works with reload.

Use `sudo crontab -e` to install this weekly root job (absolute path):

```cron
17 3 * * 1 /bin/bash /opt/powerk/deploy/scripts/update-cloudflare-ips.sh >> /var/log/powerk-cloudflare-update.log 2>&1
```

Both HTTPS downloads must succeed and pass strict CIDR validation before writes.
Invalid or empty lists leave the old config intact; apply/reload failure attempts
to restore it. Review cron output, rotate this host log using your host log policy,
and update Oracle's Cloudflare allowlist when ranges change. The script serializes
cron runs and firewall rebuilds; never edit/restart Caddy during a range update.

All image tags and installed Docker/build-tool package versions are explicit.
They are conservative known releases, **not claims of current security support**.
Review and test newer pins regularly, including `server/pyproject.toml` application
dependencies. Base-image tags are not immutable digests; deployment is not a fully
locked transitive-dependency build. The installer refuses absent apt pins instead
of silently using latest. Remote availability and the exact Caddy directives were
not verified in this offline implementation; the first-deploy validation is mandatory.

## Backups and restore

The backup container uses the same pinned Python base image as the app and only
stdlib code: no extra daemon, cron package, SQLite binary or network access. It
runs immediately at startup and every 24 hours, logs failures, and keeps the last
**14 complete snapshots** (manual backups count too). A failed run retries the
next day. Restarting the container takes another snapshot. Each timestamped UTC
directory contains `powerk.db` and `powerk.json`; partial snapshots are not retained
as completed backups. Disk exhaustion/process kills may leave hidden `.partial-*`
directories; remove them only after stopping the backup service and inspecting.

SQLite's backup API reads a consistent DB snapshot, including WAL. JSON is read
from an atomically replaced file, but the DB and JSON are **not one cross-file
transaction**. For a precisely coordinated snapshot, stop powerk, run the manual
backup, then start it. The data mount is writable to allow SQLite WAL coordination;
the backup source connection itself is opened read-only. The host `backups/`
directory is UID/GID 10001, mode 0700. Keep encrypted off-VM copies: local snapshots
do not protect against VM or disk loss.

```bash
sudo bash scripts/backup-now.sh
sudo ls -lt backups
# Substitute an actual directory name printed by the previous commands:
sudo bash scripts/restore.sh 20261012T120000.000000Z
```

Restore stops **powerk and backup**, validates both files, saves a pre-restore
snapshot when current data exists, removes stale SQLite WAL/SHM/journal files,
replaces the two files, and starts both services. Failure leaves them stopped for
inspection. Two file replacements are not atomic as a pair: after a host crash
mid-restore, rerun from the selected snapshot before starting the server. The next
normal backup resumes 14-snapshot retention, so copy important rollback snapshots
elsewhere. Restore account databases only with a compatible server version.

## Roll back to systemd

Stop the containers before rebinding 10086:

```bash
cd /opt/powerk/deploy
sudo docker compose stop powerk backup caddy
```

The untouched `/home/ubuntu/powerk` files are the simplest old-code rollback and
lose changes made after cutover. If they were modified, restore the pre-Docker
archive there **while all servers are stopped**; first preserve the current files,
remove any stale SQLite `-wal`, `-shm`, `-journal` siblings, and restore ownership
to the user in the saved systemd unit (normally `ubuntu`). Do not copy a database
with new account/schema migrations into old code unless compatibility is verified.
Keep the Docker volume and a final Docker snapshot for later recovery.

If the old UI is needed, temporarily reopen Oracle TCP 7896 and insert the matching
host ACCEPT rule **before** any 7896 REJECT; prefer restricting it to your admin IP
because the old endpoint is plain HTTP. Restore the saved unit/launch command if
needed, then:

```bash
sudo systemctl enable --now powerk.service
sudo systemctl status powerk.service
sudo journalctl -u powerk.service -n 100 --no-pager
sudo netfilter-persistent save
```

The strip reconnects on unchanged TCP 10086. The HTTPS hostname is unavailable
while Caddy is stopped; the legacy UI is on its original 7896 endpoint. Close that
temporary ingress again after the next successful cutover. Do not delete volumes,
certificates or snapshots during rollback.
