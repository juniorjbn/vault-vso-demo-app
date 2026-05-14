# vault-vso-demo-app

A single-pod demo that shows three patterns of consuming secrets from
HashiCorp Vault via the [Vault Secrets Operator (VSO)](https://developer.hashicorp.com/vault/docs/platform/k8s/vso)
side-by-side, **without ever restarting the pod**:

1. **Dynamic Secret** — short-lived PostgreSQL credentials, refreshed by a sidecar.
2. **Static Secret** — KV v2 entry mounted as a volume, refreshed in place.
3. **PKI Secret** — short-lived TLS cert, renewed before expiry.

A Flask UI renders all three sources with auto-refresh controls so you can
watch values rotate in real time while the pod uptime counter keeps growing.

## Demo

![screenshot placeholder](docs/screenshot.png)

> Add your own screenshot at `docs/screenshot.png` once you've deployed.

## What it demonstrates

- **Pattern 1** — `VaultDynamicSecret` + sidecar polling. Pod consumes new DB
  credentials within ~3 seconds of rotation. No restart, no connection storm.
- **Pattern 2** — `VaultStaticSecret` with `refreshAfter: 30s`. Edit in Vault,
  see the change in the UI within ~30s + kubelet sync (<= 60s in practice).
- **Pattern 3** — `VaultPKISecret` with 5-minute TTL and `expiryOffset: 2m`.
  Watch the serial number and validity window rotate every ~3 minutes.

```mermaid
flowchart LR
    classDef vault fill:#FFCD58,stroke:#A37A00,color:#1f2937
    classDef k8s fill:#326CE5,stroke:#1e3a8a,color:#ffffff
    classDef app fill:#22c55e,stroke:#15803d,color:#0f172a

    V[Vault Enterprise<br/>KV v2 / PKI / Database]:::vault --> VSO[Vault Secrets<br/>Operator]:::k8s
    VSO --> S1[(K8s Secret<br/>db-creds)]:::k8s
    VSO --> S2[(K8s Secret<br/>static-config)]:::k8s
    VSO --> S3[(K8s tls Secret<br/>pki-cert)]:::k8s
    S1 -- sidecar polls --> APP[Flask pod<br/>never restarts]:::app
    S2 -- volume mount --> APP
    S3 -- volume mount --> APP
```

More detail: [`docs/architecture.md`](docs/architecture.md).

## Prerequisites

- **Kubernetes cluster**, version 1.24 or newer. Any distribution; the demo
  uses only standard resources.
- **HashiCorp Vault**, OSS or Enterprise. Enterprise Namespaces work but are
  not required. Engines used:
  - `kv-v2` (Pattern 2)
  - `pki` (Pattern 3)
  - `database` (Pattern 1 — optional)
- **Vault Secrets Operator**, installed via Helm:
  ```sh
  helm repo add hashicorp https://helm.releases.hashicorp.com
  helm install vault-secrets-operator hashicorp/vault-secrets-operator \
    -n vault-secrets-operator-system --create-namespace
  ```
- **PostgreSQL reachable from Vault** for Pattern 1. If you don't have one
  handy, the easiest path is a one-pod StatefulSet inside the cluster:
  ```sh
  helm install pg oci://registry-1.docker.io/bitnamicharts/postgresql \
    -n postgres --create-namespace \
    --set auth.postgresPassword=changeme
  ```
  Then point `POSTGRES_CONN_URL` at `pg-postgresql.postgres.svc:5432`. Or set
  `SKIP_DATABASE=true` and delete the `VaultDynamicSecret` from the manifests.
- **CLI tools** on your laptop: `vault`, `kubectl`, optionally `envsubst`.

## Quick start

```sh
git clone https://github.com/juniorjbn/vault-vso-demo-app.git
cd vault-vso-demo-app

# 1. Tell setup-vault.sh how to reach Vault and your cluster.
export VAULT_ADDR="https://vault.example.com:8200"
export VAULT_TOKEN="hvs.xxxxxxxx"
export K8S_API="https://your-cluster-api:6443"
export K8S_CA_CERT_PATH="/path/to/cluster-ca.crt"
# For Pattern 1 (skip with SKIP_DATABASE=true):
export POSTGRES_CONN_URL="postgresql://{{username}}:{{password}}@pg-postgresql.postgres.svc:5432/postgres?sslmode=disable"
export POSTGRES_ADMIN_USER="postgres"
export POSTGRES_ADMIN_PASS="changeme"

# 2. Configure Vault.
cd vault
./setup-vault.sh
cd ..

# 3. Edit manifests/02-vault-connection.yaml and 03-vault-auth.yaml to match
#    your Vault address and auth mount path. Search for "CHANGE:" markers.

# 4. Apply everything.
kubectl apply -f manifests/

# 5. Wait for the pod to be Ready (first boot installs pip packages).
kubectl wait --for=condition=Ready pod -l app=vso-demo-app -n vso-demo --timeout=180s

# 6. Open the UI.
kubectl port-forward -n vso-demo svc/vso-demo-app 8080:8080
open http://localhost:8080
```

## Detailed Vault setup

`vault/setup-vault.sh` is idempotent. Re-run it anytime. It creates:

| Object | Path / Name | Purpose |
|--------|-------------|---------|
| Policy | `vso-demo` | Read access to the three demo secret paths. |
| Auth method | `kubernetes/` | Kubernetes SA token verification. |
| Auth role | `auth/kubernetes/role/vso-demo` | Binds SA `vso-demo/vso-demo-app` to the policy above. |
| KV v2 mount | `demo/` | Backing store for Pattern 2. |
| KV entry | `demo/vso-demo/static-config` | Seed data for the static-secret demo. |
| PKI mount | `pki-int/` | Issuing CA for Pattern 3 (self-signed root inside the same mount). |
| PKI role | `pki-int/roles/vso-demo-app` | Allowed CNs, TTL 5m. |
| Database mount | `database/` | Optional, for Pattern 1. |
| DB config | `database/config/postgres-demo` | PostgreSQL connection. |
| DB role | `database/roles/app-readonly` | Issues credentials with `pg_read_all_data`, lease 90s, max 2m. |

Read `vault/README.md` for the full list of overridable variables and the
policy file (`vault/policies/vso-demo.hcl`) for the exact ACL.

## Customization

Everything genuinely environment-specific lives in three places:

- **`manifests/02-vault-connection.yaml`** — Vault address and CA Secret name.
- **`manifests/03-vault-auth.yaml`** — Kubernetes auth mount path.
- **`manifests/04-vault-secrets.yaml`** — engine mount paths and role names.

If you want to rename the namespace, the cleanest path is `sed`:

```sh
NEW_NS=my-namespace
grep -rl 'vso-demo' manifests/ vault/ \
  | xargs sed -i.bak "s/vso-demo/${NEW_NS}/g"
```

(Then verify nothing important got renamed — the role `vso-demo` and the
policy `vso-demo` also use that string by default; pick a different sentinel
if you want to keep those untouched.)

Other knobs:

- **Refresh interval** — `app/app.py` saves the choice in `localStorage`; the
  default is 10s. Just pick from the dropdown.
- **Static refresh cadence** — `manifests/04-vault-secrets.yaml`, field
  `refreshAfter`.
- **PKI TTL / renewal threshold** — `manifests/04-vault-secrets.yaml`, fields
  `ttl` and `expiryOffset` on the `VaultPKISecret`.
- **Database lease TTL** — `vault/setup-vault.sh`, `default_ttl` on the role.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for sequence diagrams and
the rationale behind the sidecar pattern.

## Troubleshooting

### "VSO can't authenticate"

```
permission denied / role not found
```

Most often this is a stale cached token in the operator. Restart it:

```sh
kubectl rollout restart deploy -n vault-secrets-operator-system \
  vault-secrets-operator-controller-manager
```

Also confirm the auth role is bound to the right SA:

```sh
vault read auth/kubernetes/role/vso-demo
# bound_service_account_names should include vso-demo-app
# bound_service_account_namespaces should include vso-demo
```

### "Secret not appearing"

```sh
kubectl describe vaultstaticsecret static-config -n vso-demo
# look at the Events section at the bottom
```

Common causes: wrong mount path, wrong KV path, or the policy doesn't grant
`read` on the right `data/` and `metadata/` paths. Note that KV v2 uses
`<mount>/data/<path>` and `<mount>/metadata/<path>` — both need policy access.

### "PKI cert not rotating"

Check `spec.expiryOffset` and `spec.ttl`. The renewal trigger is "remaining
lifetime < expiryOffset". With `ttl: 5m` and `expiryOffset: 2m`, you should see
a fresh serial every ~3 minutes. Confirm with:

```sh
kubectl get secret vso-demo-pki-cert -n vso-demo -o jsonpath='{.data.tls\.crt}' \
  | base64 -d | openssl x509 -noout -serial -dates
```

### "Pod won't start"

First boot does `pip install flask cryptography pygments` (~30 seconds). The
readiness probe has `initialDelaySeconds: 45` to cover that. If the image
takes longer in your registry, bump it. If it's still failing:

```sh
kubectl logs -n vso-demo deploy/vso-demo-app -c webapp
```

### "Static refresh is slow"

`refreshAfter` controls how often VSO calls Vault, but kubelet's Secret-volume
sync runs on its own interval (default ~60s, configurable via
`--sync-frequency`). The end-to-end propagation time is roughly
`refreshAfter + kubelet-sync`. The UI reflects whatever is currently on disk.

## License

[Apache 2.0](LICENSE).

## Credits

Built around the [Vault Secrets Operator](https://github.com/hashicorp/vault-secrets-operator)
and HashiCorp Vault. The three-pattern composition is intentionally
educational — production deployments usually pick one pattern per workload.
