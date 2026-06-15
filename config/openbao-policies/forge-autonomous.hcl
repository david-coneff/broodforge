# forge-autonomous: secrets accessible without human TTY (scheduled forge jobs)
# Applied to service tokens used by: Forge process, scheduled backup jobs,
# health checks, and any automation that runs without operator presence.
path "forge/autonomous/*" {
  capabilities = ["read", "list"]
}
# TOTP codes — read-only (generate codes, never modify seeds)
path "forge/totp/code/*" {
  capabilities = ["read"]
}
# Deny all other paths explicitly
path "forge/spawn/*" {
  capabilities = ["deny"]
}
path "forge/migrate/*" {
  capabilities = ["deny"]
}
