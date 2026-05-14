# Vault setup

`setup-vault.sh` is an idempotent helper that configures everything the demo
needs inside Vault. Run it once before `kubectl apply -f manifests/`.

## What it does

1. **Policy** — writes `vso-demo` (from `policies/vso-demo.hcl`).
2. **Kubernetes auth** — enables the `kubernetes` auth method, points it at your
   API server, and creates a role `vso-demo` bound to the SA
   `vso-demo/vso-demo-app`.
3. **KV v2** — enables an engine at `demo/` and seeds
   `demo/vso-demo/static-config` with sample fields.
4. **PKI** — enables `pki-int/`, creates a self-signed root (replace with your
   own issuer in production), and adds a role `vso-demo-app` issuing 5-minute
   certs for `*.demo.local`.
5. **Database (optional)** — enables `database/`, registers a PostgreSQL
   connection, and creates the role `app-readonly` issuing 90s leases.

Every step is idempotent: re-running the script after a partial run picks up
where it left off.

## Required environment

```sh
export VAULT_ADDR="https://vault.example.com:8200"
export VAULT_TOKEN="hvs.xxxxxxxx"

# Only if your Vault is Enterprise and uses namespaces:
# export VAULT_NAMESPACE="admin"

# Used to configure the Kubernetes auth method:
export K8S_API="https://your-cluster-api:6443"
export K8S_CA_CERT_PATH="/path/to/cluster-ca.crt"
```

For Pattern 1 (database) you also need:

```sh
export POSTGRES_CONN_URL="postgresql://{{username}}:{{password}}@pg.example.com:5432/postgres?sslmode=disable"
export POSTGRES_ADMIN_USER="vaultadmin"
export POSTGRES_ADMIN_PASS="..."
```

Or opt out:

```sh
export SKIP_DATABASE=true
```

Then delete (or comment out) the `VaultDynamicSecret` resource in
`manifests/04-vault-secrets.yaml`.

## Override anything

All names default to the values used by the manifests. Override via env vars
if your environment uses different paths:

| Variable | Default | Purpose |
|----------|---------|---------|
| `K8S_AUTH_PATH` | `kubernetes` | mount of the Kubernetes auth method |
| `APP_NAMESPACE` | `vso-demo` | namespace the SA lives in |
| `APP_SA` | `vso-demo-app` | ServiceAccount name |
| `ROLE_NAME` | `vso-demo` | Vault Kubernetes role |
| `POLICY_NAME` | `vso-demo` | ACL policy name |
| `KV_MOUNT` | `demo` | KV v2 mount |
| `PKI_MOUNT` | `pki-int` | PKI mount |
| `DB_MOUNT` | `database` | Database engine mount |
| `DB_ROLE` | `app-readonly` | database role name |
| `PKI_ROLE` | `vso-demo-app` | PKI role name |

If you change any of these, update the matching field in `manifests/*.yaml`.

## Run it

```sh
cd vault
./setup-vault.sh
```

You should see "Done" at the bottom and a "Next steps" summary.
