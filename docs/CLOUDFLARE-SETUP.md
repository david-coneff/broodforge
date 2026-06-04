# Cloudflare DNS Setup Guide

**Document created:** 2026-05-31
**Review by:** 2027-05-31

This guide covers using Cloudflare as the DNS provider for your broodforge hatchery.
Cloudflare is the recommended DNS provider because it has a well-supported API,
a generous free tier, and integrates cleanly with every component broodforge uses
for TLS certificate automation.

If your domain is registered at Squarespace, GoDaddy, Namecheap, or any other
registrar, you can still use Cloudflare for DNS by changing your nameservers.
You keep your domain registration at your registrar; Cloudflare handles DNS only.

---

## What Cloudflare provides for broodforge

| Feature | How it's used |
|---|---|
| Split-horizon DNS | LAN DNS (dnsmasq) handles LAN resolution; Cloudflare handles external resolution |
| DDNS auto-update | Cloudflare API updates your A record when your WAN IP changes |
| Let's Encrypt DNS-01 | Cloudflare API proves domain ownership — no port 80 needed |
| Wildcard certificates | `*.home.example.com` covers all subdomains with one cert |
| cert-manager integration | k3s ClusterIssuer uses Cloudflare for DNS-01 challenges |

---

## Part 1 — DNS setup

### Step 1.1 — Create a Cloudflare account

1. Go to [cloudflare.com](https://cloudflare.com) → Sign Up
2. Free plan is sufficient for all broodforge needs
3. Verify your email

### Step 1.2 — Add your domain to Cloudflare

1. Dashboard → **Add a site** → enter your domain (e.g. `home.example.com`)
2. Select the **Free** plan
3. Cloudflare scans your existing DNS records. Review them:
   - Keep any MX records (email delivery)
   - Keep any existing records you need
   - Delete records you no longer need
   - You will add broodforge-specific records after setup
4. Cloudflare shows you two nameserver addresses — copy both (you need them next)

### Step 1.3 — Update nameservers at your registrar

**This step is different depending on where your domain is registered.**

**Squarespace:**
1. [domains.squarespace.com](https://domains.squarespace.com) → click your domain
2. **DNS** → **Nameservers** → **Use Custom Nameservers**
3. Delete the existing Squarespace nameservers
4. Add the two Cloudflare nameservers
5. Save. Propagation: minutes to 48 hours

**GoDaddy:**
1. GoDaddy account → **My Products** → your domain → **DNS**
2. Scroll to **Nameservers** → **Change** → **Enter my own nameservers**
3. Enter both Cloudflare nameservers → Save

**Namecheap:**
1. Dashboard → your domain → **Manage** → **Nameservers**
2. Select **Custom DNS** → enter both Cloudflare nameservers → Save

**Verify propagation:**
```bash
# Should return Cloudflare nameservers (e.g. alice.ns.cloudflare.com)
dig NS home.example.com +short
```

### Step 1.4 — Add DNS records in Cloudflare

1. Cloudflare dashboard → your domain → **DNS** → **Records** → **Add record**

Add these records (replace with your actual values):

| Type | Name | Value | Proxy | Notes |
|---|---|---|---|---|
| A | `hatchery` | your WAN IP | DNS only (grey) | The hatchery's public address |
| A | `forgejo` | your WAN IP | DNS only (grey) | If Forgejo should be externally accessible |

**Proxy status must be DNS only (grey cloud).** Broodforge nodes connect directly;
Cloudflare's HTTP proxy would intercept Headscale's and Forgejo's custom protocols.

### Step 1.5 — Create a scoped API token

Broodforge needs an API token with just enough permission to update DNS records
and create TXT records for Let's Encrypt challenges.

1. Cloudflare dashboard → top right → **My Profile** → **API Tokens**
2. **Create Token** → use the **Edit zone DNS** template
3. Configure:
   - Token name: `broodforge`
   - Permissions: **Zone / DNS / Edit** (pre-filled by template)
   - Zone resources: **Include / Specific zone / your domain**
   - TTL: leave unlimited or set a far future date
4. **Continue to summary** → **Create Token**
5. Copy the token immediately — it is shown only once

Store it in KeePass at: `Infrastructure/cloudflare/api-token`

When `forge.sh` runs, it will ask for this KeePass path and retrieve the token
automatically for DNS auto-update and certificate issuance.

---

## Part 2 — DNS auto-update (DDNS for dynamic WAN IPs)

Skip this section if your WAN IP is static.

Broodforge installs a systemd timer (`broodforge-ddns.timer`) that checks your WAN IP
every 5 minutes and updates the Cloudflare A record when it changes.

### Step 2.1 — Install dns-lexicon

```bash
pip install dns-lexicon
```

### Step 2.2 — Test the update manually

```bash
LEXICON_CLOUDFLARE_TOKEN="your-cloudflare-api-token" \
  lexicon cloudflare update home.example.com A \
  --name hatchery --content "$(curl -s ifconfig.me)"
```

Expected: no error output, Cloudflare A record updates to your current WAN IP.

### Step 2.3 — Configure via broodforge wizard

During forging, `forge.sh` runs `setup_ddns.py` which handles the configuration.
If you need to configure it manually afterwards:

```bash
python3 proxmox-bootstrap/setup_ddns.py \
  --state proxmox-bootstrap/bootstrap-state.json
```

Select **Cloudflare**, enter your domain zone, record name, and the KeePass path
for the API token. The wizard tests the connection before saving.

### Step 2.4 — Monitor the timer

```bash
# Check timer status
systemctl status broodforge-ddns.timer

# Check last few update runs
journalctl -u broodforge-ddns.service -n 20

# Force an immediate update
systemctl start broodforge-ddns.service
```

---

## Part 3 — Let's Encrypt TLS certificates

Broodforge uses **DNS-01 challenges** for all Let's Encrypt certificates. This means:
- Port 80 does not need to be open — the challenge is answered via DNS, not HTTP
- Wildcard certificates are supported (`*.home.example.com`)
- Works even if the hatchery is behind a strict firewall

### Certificate architecture

| Layer | Tool | Cert covers |
|---|---|---|
| Proxmox host services (Headscale, nginx) | certbot | `hatchery.home.example.com`, `*.home.example.com` |
| k3s workloads (Forgejo, monitoring, apps) | cert-manager | Per-service certs via ClusterIssuer |

The wildcard cert on the host covers all externally-reachable host-level services.
cert-manager handles per-service certs inside k3s automatically.

> **Two tools are available for host-level certificates. Choose one:**
> - **certbot** (Part 3a) — the EFF's official Let's Encrypt client; best-known,
>   has an official Cloudflare plugin, works well with nginx.
> - **acme.sh** (Part 3a-alt) — a pure-shell alternative; no Python dependencies,
>   supports Cloudflare natively, same DNS-01 challenge, simpler if you prefer to
>   avoid Python tooling on the host. Used by the DuckDNS path as the primary tool;
>   optional here for Cloudflare.
>
> Both produce identical results. Pick one and use it consistently.
> cert-manager (Part 3b) is the same regardless of which host-level tool you chose.

### Part 3a — Host-level certificate via certbot (recommended)

This cert is used by Headscale and any host-level nginx/reverse-proxy.
It is obtained during forge phase-03 or phase-04, before k3s exists.

#### Install certbot and the Cloudflare plugin

```bash
apt install certbot python3-certbot-dns-cloudflare
```

#### Create the Cloudflare credentials file

```bash
mkdir -p /etc/broodforge
cat > /etc/broodforge/cloudflare.ini << 'EOF'
# Cloudflare API token for Let's Encrypt DNS-01 challenges
# Retrieve from KeePass: Infrastructure/cloudflare/api-token
dns_cloudflare_api_token = PASTE_TOKEN_HERE
EOF
chmod 600 /etc/broodforge/cloudflare.ini
```

During forging, `forge.sh` writes this file using the token retrieved from KeePass.
The operator never pastes the token manually.

#### Obtain the wildcard certificate

```bash
certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /etc/broodforge/cloudflare.ini \
  --dns-cloudflare-propagation-seconds 30 \
  -d "hatchery.home.example.com" \
  -d "*.home.example.com" \
  --email admin@home.example.com \
  --agree-tos \
  --non-interactive
```

The wildcard `*.home.example.com` covers every subdomain in your cluster.
Certificates land in `/etc/letsencrypt/live/hatchery.home.example.com/`.

#### Configure Headscale to use the certificate

In `/etc/headscale/config.yaml`:
```yaml
tls_cert_path: /etc/letsencrypt/live/hatchery.home.example.com/fullchain.pem
tls_key_path: /etc/letsencrypt/live/hatchery.home.example.com/privkey.pem
```

Restart Headscale after the cert is issued:
```bash
systemctl restart headscale
```

#### Auto-renewal

certbot installs a systemd timer (`certbot.timer`) that renews certs automatically
when they are within 30 days of expiry. After renewal, Headscale needs to reload:

```bash
# Create a deploy hook that reloads Headscale after renewal
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-headscale.sh << 'EOF'
#!/bin/bash
systemctl reload headscale || systemctl restart headscale
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-headscale.sh
```

Verify renewal works:
```bash
certbot renew --dry-run
```

---

### Part 3a-alt — Host-level certificate via acme.sh (alternative)

Use this instead of certbot if you prefer a shell-only approach with no Python dependencies.
The result is identical: a wildcard cert at a stable path, auto-renewed.

#### Install acme.sh

```bash
curl https://get.acme.sh | sh -s email=admin@home.example.com
source ~/.bashrc
```

#### Issue the certificate using Cloudflare DNS-01

```bash
export CF_Token="YOUR-CLOUDFLARE-API-TOKEN"

~/.acme.sh/acme.sh --issue \
  --dns dns_cf \
  -d "hatchery.home.example.com" \
  -d "*.home.example.com" \
  --server letsencrypt \
  --dnssleep 30
```

`CF_Token` is the same API token created in Step 1.5. acme.sh uses the environment
variable `CF_Token` for Cloudflare authentication.

#### Install cert to a stable path

```bash
mkdir -p /etc/broodforge/ssl

~/.acme.sh/acme.sh --install-cert \
  -d "hatchery.home.example.com" \
  --cert-file     /etc/broodforge/ssl/cert.pem \
  --key-file      /etc/broodforge/ssl/key.pem \
  --fullchain-file /etc/broodforge/ssl/fullchain.pem \
  --reloadcmd "systemctl reload headscale 2>/dev/null || systemctl restart headscale"
```

Configure Headscale to use `/etc/broodforge/ssl/fullchain.pem` and
`/etc/broodforge/ssl/key.pem` — same paths as the DuckDNS guide, so forge scripts
can use the same Headscale config template for both providers.

acme.sh installs a cron entry for auto-renewal. Verify:
```bash
crontab -l | grep acme
~/.acme.sh/acme.sh --renew -d "hatchery.home.example.com" --force --staging
```

---

### Part 3b — k3s workload certificates (cert-manager)

cert-manager runs inside k3s and issues per-service TLS certificates automatically.
It uses the same Cloudflare API token as certbot.

#### Create the Cloudflare API token secret in k3s

```bash
kubectl create namespace cert-manager

kubectl create secret generic cloudflare-api-token \
  --namespace cert-manager \
  --from-literal=api-token="$(cat /etc/broodforge/cloudflare.ini \
    | grep api_token | awk '{print $3}')"
```

During forging, `forge.sh` generates this secret from KeePass — the operator
does not paste the token manually.

#### Create the ClusterIssuer

```yaml
# /etc/broodforge/k8s/clusterissuer-cloudflare.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@home.example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
```

```bash
kubectl apply -f /etc/broodforge/k8s/clusterissuer-cloudflare.yaml
```

#### Request a certificate for a service

Any k3s service can now request a cert by annotating its Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: forgejo
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
  - hosts:
    - forgejo.home.example.com
    secretName: forgejo-tls
  rules:
  - host: forgejo.home.example.com
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

cert-manager sees the annotation, creates a Certificate resource, performs a DNS-01
challenge via Cloudflare, and stores the cert in `forgejo-tls`. The Ingress serves
HTTPS automatically. Renewal is fully automatic.

#### Verify cert-manager is working

```bash
# Check ClusterIssuer status
kubectl describe clusterissuer letsencrypt-prod

# Check certificate status for a service
kubectl describe certificate forgejo-tls -n default

# Watch the challenge process
kubectl get challenges -A -w
```

---

## Forge-time setup summary

When `forge.sh` runs, it handles all of the above automatically. The operator
provides (once, at forge time):
1. Domain name → stored in `bootstrap-state.json host_identity.domain`
2. KeePass path for Cloudflare API token → retrieved at each step
3. Email for Let's Encrypt account → stored in bootstrap-state.json
4. Whether WAN IP is static or dynamic → configures DDNS timer if dynamic

Everything else — certbot install, credentials file, certificate issuance, Headscale
config, k8s secret, ClusterIssuer — is automated.

---

## Troubleshooting

**certbot: DNS propagation timeout**
Increase `--dns-cloudflare-propagation-seconds` to 60 or 120. Cloudflare propagates
quickly but Let's Encrypt sometimes polls before the change is visible.

**cert-manager challenge stuck**
```bash
kubectl describe challenge -A
```
Check the Cloudflare API token has `Zone / DNS / Edit` permission for the correct zone.

**Headscale shows TLS error after cert renewal**
The deploy hook should handle this. Check manually:
```bash
systemctl status headscale
# If not running:
certbot renew --force-renewal
systemctl restart headscale
```

**Cloudflare shows "This site can't be reached"**
Check that the A record's proxy status is **DNS only (grey)**, not proxied (orange).
Headscale's gRPC protocol is not compatible with Cloudflare's HTTP proxy.

**Nameserver propagation check**
```bash
dig NS home.example.com @8.8.8.8 +short
# Should show alice.ns.cloudflare.com, bob.ns.cloudflare.com (or your assigned NS)
```
