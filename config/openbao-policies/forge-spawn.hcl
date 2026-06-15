# forge-spawn: secrets scoped to spawn-phase VM provisioning
# Applied to service tokens used by: Spawn process, cloud-init injection,
# VM template deployment, first-boot credential seeding.
path "forge/spawn/*" {
  capabilities = ["read", "list"]
}
# Spawn also needs SSH keys and Proxmox API credentials
path "forge/autonomous/proxmox/*" {
  capabilities = ["read"]
}
path "forge/autonomous/ssh/*" {
  capabilities = ["read"]
}
# Deny migration scope
path "forge/migrate/*" {
  capabilities = ["deny"]
}
