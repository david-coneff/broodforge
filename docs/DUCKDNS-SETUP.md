# DuckDNS Setup Guide

**Document created:** 2026-05-31
**Review by:** 2027-05-31

This guide covers using DuckDNS as the dynamic DNS (DDNS) provider for your
broodforge hatchery. DuckDNS is a free service that provides subdomains under
`duckdns.org` (e.g. `myhatchery.duckdns.org`). It is a good option if you do not
have your own domain or want the simplest possible setup.

**Trade-off vs Cloudflare:** DuckDNS is free and simple, but your hatchery's address
will be `myhatchery.duckdns.org` rather than a subdomain of your own domain. If you
have your own domain, consider the Cloudflare path (see `docs/CLOUDFLARE-SETUP.md`)
for a cleaner address and wildcard certificate support.

---

## What DuckDNS provides for broodforge

| Feature | Notes |
|---|---|
| Free subdomain | `myhatchery.duckdns.org` → your WAN IP |
| DDNS auto-update | Simple HTTPS GET, no library required |
| Let's Encrypt DNS-01 | Via acme.sh — DNS-01 challenge supported |
| Wildcard certificates | `*.myhatchery.duckdns.org` — supported via DNS-01 |
| cert-manager integration | Via acme-dns relay or manual cert sync |

---

## Part 1 — DuckDNS DDNS setup

### Step 1.1 — Create a DuckDNS account and subdomain

1. Go to [duckdns.org](https://www.duckdns.org)
2. Sign in with GitHub, Google, Twitter, or Reddit (any works)
3. In the **sub domain** field, enter your chosen name (e.g. `myhatchery`)
4. Click **add domain**
5. Your subdomain is now `myhatchery.duckdns.org`
6. Copy your **token** — shown on the main dashboard (a UUID like `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

Your token is the only credential DuckDNS requires. Store it in KeePass at:
`Infrastructure/duckdns/token`

### Step 1.2 — Test the update

DuckDNS updates via a single HTTPS GET. No client software required for the update
itself.

```bash
# Update to your current WAN IP (leave ip= blank for auto-detect)
curl -s "https://www.duckdns.org/update?domains=myhatchery&token=YOUR-TOKEN&ip="
```

Expected response: `OK`

If you see `KO`, your token is wrong or the subdomain doesn't exist in your account.

### Step 1.3 — Configure via broodforge wizard

During forging, `forge.sh` runs `setup_ddns.py` which handles configuration.
To configure manually afterwards:

```bash
python3 proxmox-bootstrap/setup_ddns.py \
  --state proxmox-bootstrap/bootstrap-state.json
```

Select **DuckDNS**, enter your subdomain name and the KeePass path for your token.
The wizard tests the connection before saving.

### Step 1.4 — How broodforge runs the auto-update

Broodforge installs a systemd timer that calls the DuckDNS update URL every 5 minutes:

```bash
# Check timer status
systemctl status broodforge-ddns.timer

# Check recent update runs
journalctl -u broodforge-ddns.service -n 20

# Force an immediate update
systemctl start broodforge-ddns.service
```

The update script (`update-dns.py`) fetches your current WAN IP, compares to the
cached last IP, and only calls DuckDNS when the IP has changed.

---

## Part 2 — Let's Encrypt TLS certificates

Broodforge uses **acme.sh** for Let's Encrypt certificates when DuckDNS is selected.
acme.sh is a shell script with no dependencies that has built-in DuckDNS DNS-01
challenge support.

**Why acme.sh instead of certbot for DuckDNS:** certbot's DuckDNS plugin is a
third-party community plugin with inconsistent maintenance. acme.sh has first-class
DuckDNS support and is actively maintained. For the Cloudflare path, certbot is used
(it has an official Cloudflare plugin). For DuckDNS, acme.sh is used.

### Certificate architecture

| Layer | Tool | Cert covers |
|---|---|
| Proxmox host services (Headscale, nginx) | acme.sh | `myhatchery.duckdns.org`, `*.myhatchery.duckdns.org` |
| k3s workloads | Cert synced as k8s secret | Same cert mounted in cluster |

Unlike the Cloudflare path, cert-manager's DNS-01 solver does not natively support
DuckDNS. Broodforge handles k3s certificate distribution by syncing the acme.sh-issued
cert into a Kubernetes TLS secret and refreshing it on renewal.

### Part 2a — Host-level certificate (acme.sh)

#### Install acme.sh

```bash
curl https://get.acme.sh | sh -s email=admin@myhatchery.duckdns.org
# Reload shell to get acme.sh in PATH:
source ~/.bashrc
```

acme.sh installs to `~/.acme.sh/` and sets up a cron job for auto-renewal.

#### Issue the certificate

```bash
export DuckDNS_Token="YOUR-DUCKDNS-TOKEN"

~/.acme.sh/acme.sh --issue \
  --dns dns_duckdns \
  -d myhatchery.duckdns.org \
  -d "*.myhatchery.duckdns.org" \
  --server letsencrypt \
  --keylength 2048 \
  --dnssleep 60
```

`--dnssleep 60` gives DuckDNS time to propagate the TXT record before Let's Encrypt
checks it. If the challenge fails, increase to 120.

This creates a wildcard cert covering `myhatchery.duckdns.org` and all subdomains
(`*.myhatchery.duckdns.org`). Even though broodforge may use subdomains internally,
they all resolve to the same IP, so the wildcard covers them.

#### Install the certificate to a stable location

acme.sh keeps certs in its own directory but can copy them to a stable path and
run a command after each renewal:

```bash
mkdir -p /etc/broodforge/ssl

~/.acme.sh/acme.sh --install-cert \
  -d myhatchery.duckdns.org \
  --cert-file     /etc/broodforge/ssl/cert.pem \
  --key-file      /etc/broodforge/ssl/key.pem \
  --fullchain-file /etc/broodforge/ssl/fullchain.pem \
  --reloadcmd "systemctl reload headscale nginx 2>/dev/null || systemctl restart headscale"
```

After every successful renewal, acme.sh copies the cert files and runs the reload command.

#### Configure Headscale to use the certificate

In `/etc/headscale/config.yaml`:
```yaml
tls_cert_path: /etc/broodforge/ssl/fullchain.pem
tls_key_path: /etc/broodforge/ssl/key.pem
```

Restart Headscale:
```bash
systemctl restart headscale
```

#### Verify auto-renewal

```bash
# Test renewal without actually renewing
~/.acme.sh/acme.sh --renew -d myhatchery.duckdns.org --force --staging

# Check the cron job acme.sh installed
crontab -l | grep acme

# View cron logs
journalctl -u cron -n 20
```

acme.sh renews automatically when the cert is within 30 days of expiry.

### Part 2b — k3s workload certificates (cert sync)

cert-manager does not have native DuckDNS DNS-01 support. Broodforge takes a
simpler approach: the wildcard cert issued by acme.sh on the Proxmox host is synced
into a Kubernetes TLS secret and refreshed whenever acme.sh renews.

#### Create the Kubernetes TLS secret

```bash
kubectl create secret tls duckdns-wildcard-tls \
  --namespace default \
  --cert=/etc/broodforge/ssl/fullchain.pem \
  --key=/etc/broodforge/ssl/key.pem
```

For other namespaces (monitoring, applications), copy the secret:
```bash
kubectl get secret duckdns-wildcard-tls -o yaml \
  | sed 's/namespace: default/namespace: monitoring/' \
  | kubectl apply -f -
```

#### Auto-sync the secret on cert renewal

Add a sync step to the acme.sh reload command:

```bash
~/.acme.sh/acme.sh --install-cert \
  -d myhatchery.duckdns.org \
  --cert-file     /etc/broodforge/ssl/cert.pem \
  --key-file      /etc/broodforge/ssl/key.pem \
  --fullchain-file /etc/broodforge/ssl/fullchain.pem \
  --reloadcmd "/opt/broodforge/sync-cert-to-k8s.sh"
```

Create `/opt/broodforge/sync-cert-to-k8s.sh`:
```bash
#!/bin/bash
# Sync renewed DuckDNS wildcard cert into Kubernetes TLS secrets
set -e

for NS in default monitoring applications; do
  kubectl create secret tls duckdns-wildcard-tls \
    --namespace "$NS" \
    --cert=/etc/broodforge/ssl/fullchain.pem \
    --key=/etc/broodforge/ssl/key.pem \
    --dry-run=client -o yaml | kubectl apply -f -
done

echo "[cert-sync] Wildcard cert synced to namespaces: default monitoring applications"
```

```bash
chmod +x /opt/broodforge/sync-cert-to-k8s.sh
```

#### Use the cert in Ingress resources

k3s Ingress resources reference the pre-existing TLS secret rather than requesting
a cert from cert-manager:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: forgejo
  namespace: default
spec:
  tls:
  - hosts:
    - forgejo.myhatchery.duckdns.org
    secretName: duckdns-wildcard-tls   # uses the synced cert
  rules:
  - host: forgejo.myhatchery.duckdns.org
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: forgejo
            port:
              number: 3000
```

When acme.sh renews the cert, `sync-cert-to-k8s.sh` updates the secret, and
Kubernetes serves the new cert on the next request (no Ingress restart needed).

---

## Part 3 — Configuration in bootstrap-state.json

After `setup_ddns.py` completes, these fields are set in bootstrap-state.json:

```json
"network_topology": {
  "ddns_provider":              "duckdns",
  "ddns_zone":                  "duckdns.org",
  "ddns_record":                "myhatchery",
  "ddns_credential_reference":  "Infrastructure/duckdns/token",
  "ssl_provider":               "acme.sh",
  "ssl_method":                 "dns-01-duckdns",
  "ssl_cert_path":              "/etc/broodforge/ssl/fullchain.pem",
  "ssl_key_path":               "/etc/broodforge/ssl/key.pem"
}
```

The documentation engine uses these fields to pre-populate recovery runbook steps
for certificate retrieval and renewal.

---

## Forge-time setup summary

When `forge.sh` runs, it handles all of the above automatically. The operator
provides (once, at forge time):
1. DuckDNS subdomain name → stored in `bootstrap-state.json host_identity.fqdn`
   (becomes `{subdomain}.duckdns.org`)
2. KeePass path for DuckDNS token → retrieved at each step
3. Email for Let's Encrypt account → stored in bootstrap-state.json

Everything else — acme.sh install, cert issuance, Headscale config, k8s secret
creation, sync script, DDNS timer — is automated.

---

## Troubleshooting

**acme.sh: DuckDNS DNS-01 challenge fails**
Increase `--dnssleep` to 120 seconds. DuckDNS propagation is usually fast but
Let's Encrypt's validation servers occasionally poll before the TXT record is visible.

**acme.sh: "Verify error: DNS problem"**
Check that the TXT record was actually created:
```bash
dig TXT _acme-challenge.myhatchery.duckdns.org +short
```
If empty, the DuckDNS token may be wrong or the API call failed.

**k8s secret not updating after cert renewal**
Check the sync script ran:
```bash
journalctl -u cron -n 20 | grep acme
```
Run manually: `/opt/broodforge/sync-cert-to-k8s.sh`

**Headscale shows expired cert**
acme.sh's reload command should handle this. Force:
```bash
~/.acme.sh/acme.sh --renew -d myhatchery.duckdns.org --force
systemctl restart headscale
```

**DDNS update failing**
```bash
# Test directly
curl -s "https://www.duckdns.org/update?domains=myhatchery&token=YOUR-TOKEN&ip="
# Should return OK
```
Check that your token in KeePass matches the one on the DuckDNS dashboard.

---

## Limitations compared to Cloudflare

| Feature | DuckDNS | Cloudflare |
|---|---|---|
| Own domain | No — `*.duckdns.org` only | Yes — your domain |
| cert-manager native integration | No — manual sync | Yes — ClusterIssuer |
| Wildcard cert | Yes (via acme.sh) | Yes (via certbot) |
| DDNS for your own domain | No | Yes |
| Additional DNS records | No | Yes |
| API reliability | Good | Excellent |

If you outgrow DuckDNS and acquire your own domain, migrating to Cloudflare involves:
1. Setting up Cloudflare (this guide → CLOUDFLARE-SETUP.md)
2. Updating `host_identity.fqdn` and `network_topology.*` in bootstrap-state.json
3. Re-issuing certs with certbot
4. Updating the ClusterIssuer to Cloudflare DNS-01
5. Updating any external references to the old duckdns.org address

Broodforge forge-time documentation should be re-generated after this migration
(`engine.py --mode bootstrap --manifest proxmox-bootstrap/bootstrap-state.json`).
