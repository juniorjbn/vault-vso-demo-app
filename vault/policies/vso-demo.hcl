# Policy granted to the Kubernetes auth role "vso-demo".
# Lets VSO read the three demo secrets on behalf of the pod's ServiceAccount.

# Pattern 1: Dynamic — read DB credentials for the demo role.
path "database/creds/app-readonly" {
  capabilities = ["read"]
}

# Pattern 2: Static — read KV v2 entry and its metadata.
path "demo/data/vso-demo/static-config" {
  capabilities = ["read"]
}
path "demo/metadata/vso-demo/static-config" {
  capabilities = ["read"]
}

# Pattern 3: PKI — issue certs against the demo PKI role.
path "pki-int/issue/vso-demo-app" {
  capabilities = ["create", "update"]
}
