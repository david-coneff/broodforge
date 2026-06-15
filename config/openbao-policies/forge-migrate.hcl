# forge-migrate: secrets scoped to VM migration and Phoenix operations
# Applied to service tokens used by: Phoenix process, VM migration tasks,
# cross-node credential synchronisation.
path "forge/migrate/*" {
  capabilities = ["read", "list"]
}
# Migration needs Proxmox credentials on both source and dest
path "forge/autonomous/proxmox/*" {
  capabilities = ["read"]
}
# Deny spawn secrets (migration doesn't provision new VMs)
path "forge/spawn/*" {
  capabilities = ["deny"]
}
