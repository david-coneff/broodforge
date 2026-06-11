# Broodforge User Registry

The user registry is the single source of truth for who should have accounts on broodforge-managed Kubernetes services. It lives above the Kubernetes layer in `config/user-registry.json` so that after a full cluster rebuild, all users can be re-provisioned automatically without asking anyone to re-register.

## Concepts

**Disposition** — the lifecycle state of a user record:

| Disposition | Meaning |
|---|---|
| `active` | User is provisioned by default on every rebuild |
| `archived` | Record preserved for audit; user skipped during provisioning |
| `pending-deletion` | Scheduled for removal; skipped during provisioning |

**Service enrollment** — each user has a `services` dict mapping service name → enrollment metadata. A user can be enrolled in all services or a granular subset decided by the sysadmin.

**Key throw-away** — after a user acknowledges their onboarding credentials, the admin can destroy the master copy (`forge-throw-away-key.sh`). Once thrown away, the admin can still delete the account but can no longer log in as the user. This achieves *zero-knowledge admin access* for that user's data.

## KeePass path convention

All per-user credentials are stored in the master KeePass database under:

```
Broodforge/users/<username>/<service>/password
Broodforge/users/<username>/<service>/totp-secret
```

Additional credential types (when applicable):

```
Broodforge/users/<username>/<service>/api-key
Broodforge/users/<username>/<service>/preshared-key
```

Scripts and the Python registry helper use `keeass_entry_path(username, service, field)` (in `user_registry.py`) to generate these paths consistently.

## Full lifecycle

### 1. Onboard a new user

```bash
# Generate credentials, store in KeePass, produce HTML onboarding package
bash scripts/forge-onboard-user.sh \
    --user alice \
    --display-name "Alice Smith" \
    --email alice@example.com \
    --services vaultwarden,headscale,gitea \
    --output /secure/path/alice-onboarding.html

# Optional: also generate PDF
bash scripts/forge-onboard-user.sh ... --also-pdf
```

The onboarding package (HTML) contains:
- Username and service-specific password for each enrolled service
- TOTP QR code and manual entry secret for each service
- Security notices and zero-knowledge property explanation

Deliver the HTML file to the user via an encrypted/secure channel (Signal, encrypted email, in person).

### 2. Provision accounts in services

```bash
# Re-provision all active users into all enrolled services
bash scripts/forge-provision-users.sh

# Provision a single user
bash scripts/forge-provision-users.sh --user alice

# Provision a specific service only
bash scripts/forge-provision-users.sh --service gitea

# Full rebuild with summary report
bash scripts/forge-provision-users.sh --rebuild-mode
```

### 3. Add a service to an existing user

```bash
# Enroll alice in nextcloud after it is deployed
bash scripts/forge-onboard-user.sh \
    --add-service alice nextcloud \
    --output /secure/path/alice-nextcloud.html
```

This generates credentials for just that one service, stores them in KeePass, and renders a single-service credential snippet.

### 4. Throw away the master copy of credentials (zero-knowledge)

Once the user has confirmed they've saved their credentials:

```bash
# Throw away admin copy for all services
bash scripts/forge-throw-away-key.sh --user alice

# Throw away for one service only
bash scripts/forge-throw-away-key.sh --user alice --service vaultwarden
```

After this:
- The admin no longer holds the user's password for that service
- On future rebuilds, the user receives a temporary password and a reset notification
- The admin can still delete the account but cannot impersonate the user

### 5. Offboard a user

```bash
# Offboard from all services (sets disposition → archived)
bash scripts/forge-offboard-user.sh --user alice

# Offboard from one service only
bash scripts/forge-offboard-user.sh --user alice --service gitea

# Fully remove from registry after offboarding
bash scripts/forge-offboard-user.sh --user alice --remove-from-registry
```

Offboarding per service:
1. Deletes the service account (via `_offboard_<service>()` adapter)
2. Deletes KeePass credentials (skipped if key was already thrown away)
3. Removes service enrollment from `user-registry.json`

## Adding a new service

When a new service is added to the cluster (e.g. Nextcloud), two adapters are needed:

### Provisioning adapter (`scripts/forge-provision-users.sh`)

Add a `_provision_<service>()` function:

```bash
_provision_nextcloud() {
  local username="$1"
  local email="$2"
  local password="$3"
  local flow="$4"   # provision | reset

  [[ $DRY_RUN -eq 1 ]] && { info "  [dry-run] nextcloud: ${flow} ${username}"; return 0; }

  local NC_POD
  NC_POD=$(kubectl get pod -l app=nextcloud -o jsonpath='{.items[0].metadata.name}') \
    || { warn "  nextcloud pod not found"; return 1; }

  case "$flow" in
    provision)
      kubectl exec "$NC_POD" -- php occ user:add \
        --display-name "$username" \
        --password-from-env "$username" \
        ... # implement per Nextcloud OCC CLI
      ;;
    reset)
      # generate temp password, notify user
      ...
      ;;
  esac
}
```

Then add `nextcloud)` to the `_provision_user_service()` dispatcher.

### Offboarding adapter (`scripts/forge-offboard-user.sh`)

Add a `_offboard_nextcloud()` function:

```bash
_offboard_nextcloud() {
  local username="$1"

  local NC_POD
  NC_POD=$(kubectl get pod -l app=nextcloud -o jsonpath='{.items[0].metadata.name}') \
    || { warn "  nextcloud pod not found"; return 1; }

  kubectl exec "$NC_POD" -- php occ user:delete "$username" \
    && info "  ✓ nextcloud: deleted ${username}" \
    || { warn "  nextcloud: could not delete ${username}"; return 1; }
}
```

Then add `nextcloud)` to the `_offboard_service_account()` dispatcher.

### Convention checklist for each new service

- [ ] `_provision_<service>()` in `forge-provision-users.sh` — handles both `provision` and `reset` flows
- [ ] `_offboard_<service>()` in `forge-offboard-user.sh`
- [ ] Service has a meaningful TOTP setup (add to onboarding if applicable)
- [ ] Any required k8s secrets documented (e.g. `vaultwarden-admin-token`)
- [ ] Update this document with service-specific notes

## User registry CLI reference

```bash
python3 proxmox-bootstrap/user_registry.py [--registry config/user-registry.json] <command>

# View
--list                            List all users and their service enrollments

# Create
--add --username alice \
  --display-name "Alice Smith" \
  --email alice@example.com \
  --services vaultwarden,headscale,gitea

# Modify enrollment
--add-service alice nextcloud     Enroll in an additional service
--remove-service alice nextcloud  Remove a service enrollment (creds deleted first)

# Lifecycle
--disposition alice archived      Set disposition: active | archived | pending-deletion
--throw-away-key alice vaultwarden  Mark admin copy of key as discarded
--acknowledge alice               Mark onboarding as acknowledged by user

# Removal
--remove-user --username alice    Remove user record entirely

# Rebuild
--users-for-rebuild               TSV: username, service, flow (provision|reset)

# Init
--init                            Create empty registry file
```

## Zero-knowledge properties

Broodforge aims for a *privacy-respecting* multi-user setup where the sysadmin operates services on behalf of users but does not have standing access to their data.

| Property | Implementation |
|---|---|
| Service data encrypted | Vaultwarden encrypts vault contents client-side; only user's master password decrypts |
| Password hashes only | Services store bcrypt/argon2 hashes; plaintext never touches service storage |
| Key throw-away | Once thrown away, admin copy in KeePass is gone; rebuild uses reset flow |
| Admin can delete accounts | Sysadmin retains ability to delete abandoned accounts without impersonating user |
| TOTP required | Each service has a separate TOTP secret; compromising one service does not compromise others |

## Sidecar GUI integration points

The user registry is designed to be surfaced in the broodforge sidecar GUI:

- **User list view** — read `config/user-registry.json`, render disposition badges, service enrollment chips, and key-thrown-away indicators
- **Onboard action** — shell out to `forge-onboard-user.sh`, display the generated HTML package path
- **Throw-away action** — shell out to `forge-throw-away-key.sh` with confirmation dialog
- **Provision action** — shell out to `forge-provision-users.sh --user <name>` or `--service <name>`
- **Offboard action** — shell out to `forge-offboard-user.sh` with service selection and confirmation
- **Rebuild view** — call `user_registry.py --users-for-rebuild`, show TSV as a pre-flight checklist before `forge-provision-users.sh --rebuild-mode`
