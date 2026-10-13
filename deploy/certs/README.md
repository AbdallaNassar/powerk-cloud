Place these **three files** here before starting Caddy:

| Filename | Source |
| --- | --- |
| `origin.pem` | Cloudflare dashboard: your zone -> SSL/TLS -> Origin Server -> Create Certificate. Choose RSA, include `powerk.example.com`, and select 15 years. Save the PEM certificate. |
| `origin.key` | Private key displayed with that Origin CA certificate. Save it immediately; Cloudflare will not display it again. |
| `cloudflare-origin-pull-ca.pem` | Cloudflare's public CA for validating the **client** certificate presented by Authenticated Origin Pulls (AOP). This is not the Origin CA server issuer. |

Official AOP documentation:
[Authenticated Origin Pulls](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/).
CA download:
[origin-pull-ca.pem](https://developers.cloudflare.com/ssl/static/origin_pull_ca.pem).

On the VPS, from `deploy/`:

```bash
sudo curl --fail --show-error --location --proto '=https' --proto-redir '=https' \
  https://developers.cloudflare.com/ssl/static/origin_pull_ca.pem \
  -o certs/cloudflare-origin-pull-ca.pem
sudo chown root:root certs/*.pem certs/*.key
sudo chmod 700 certs
sudo chmod 600 certs/origin.key
sudo chmod 644 certs/origin.pem certs/cloudflare-origin-pull-ca.pem
sudo openssl x509 -in certs/origin.pem -noout -subject -issuer -dates -ext subjectAltName
sudo openssl x509 -in certs/cloudflare-origin-pull-ca.pem -noout -subject -issuer -dates
```

Caddy runs as container root with only `NET_BIND_SERVICE`, so it can read the
root-owned key through the read-only mount. The app and backup containers never
receive the certificates. Never commit any key or certificate; the gitignore and
dockerignore exclude them. Keep an encrypted copy of the private key elsewhere.

In Cloudflare, enable **Authenticated Origin Pulls** for this zone under SSL/TLS ->
Origin Server. This deployment uses the standard Cloudflare-managed AOP client
certificate; account-specific custom AOP certificates require a different trust
anchor. The standard certificate proves a connection came from Cloudflare, not
from a particular Cloudflare account. The hostname and firewall provide the other
restrictions.

Origin CA certificates are trusted by Cloudflare, not directly by browsers. The
visitor sees Cloudflare's public edge certificate. Origin port 80 and ACME are
unused. Monitor **both** certificate expiry dates (the AOP CA does not inherit the
server certificate's 15-year lifetime). Replace files in this directory, validate,
then reload Caddy using the commands in the deployment README.
