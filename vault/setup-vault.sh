#!/usr/bin/env bash
# Configures HashiCorp Vault for the vault-vso-demo-app.
#
# Prerequisites:
#   - Vault Enterprise (or OSS) running and unsealed.
#   - VAULT_ADDR + VAULT_TOKEN exported. Token must have permission to:
#       * enable / configure secrets engines (database, kv-v2, pki)
#       * enable / configure the kubernetes auth method
#       * write ACL policies
#   - Optionally: VAULT_NAMESPACE for Vault Enterprise namespaces.
#   - PostgreSQL reachable from Vault (for Pattern 1). If not, set
#     SKIP_DATABASE=true and the database engine will not be configured.
#   - kubectl configured against the target cluster (used to read the
#     ServiceAccount JWT for the Kubernetes auth method).
#
# Variables you can override (export before running):
#   VAULT_ADDR              e.g. https://vault.example.com:8200
#   VAULT_TOKEN             e.g. hvs.xxxx
#   VAULT_NAMESPACE         (optional, Enterprise only)
#   K8S_AUTH_PATH           default: kubernetes
#   K8S_API                 e.g. https://k8s.example.com:6443
#   K8S_CA_CERT_PATH        path to the cluster CA file
#   APP_NAMESPACE           default: vso-demo
#   APP_SA                  default: vso-demo-app
#   ROLE_NAME               default: vso-demo
#   POLICY_NAME             default: vso-demo
#   KV_MOUNT                default: demo
#   PKI_MOUNT               default: pki-int
#   DB_MOUNT                default: database
#   DB_ROLE                 default: app-readonly
#   PKI_ROLE                default: vso-demo-app
#   POSTGRES_CONN_URL       e.g. postgresql://{{username}}:{{password}}@pg.example.com:5432/postgres?sslmode=disable
#   POSTGRES_ADMIN_USER     e.g. vaultadmin
#   POSTGRES_ADMIN_PASS     password for the admin user
#   SKIP_DATABASE           "true" to skip Pattern 1 setup (default: false)
#
# Usage:
#   export VAULT_ADDR=...
#   export VAULT_TOKEN=...
#   export K8S_API=https://...
#   export K8S_CA_CERT_PATH=/path/to/ca.crt
#   ./setup-vault.sh
set -euo pipefail

: "${VAULT_ADDR:?VAULT_ADDR is required}"
: "${VAULT_TOKEN:?VAULT_TOKEN is required}"

K8S_AUTH_PATH="${K8S_AUTH_PATH:-kubernetes}"
APP_NAMESPACE="${APP_NAMESPACE:-vso-demo}"
APP_SA="${APP_SA:-vso-demo-app}"
ROLE_NAME="${ROLE_NAME:-vso-demo}"
POLICY_NAME="${POLICY_NAME:-vso-demo}"
KV_MOUNT="${KV_MOUNT:-demo}"
PKI_MOUNT="${PKI_MOUNT:-pki-int}"
DB_MOUNT="${DB_MOUNT:-database}"
DB_ROLE="${DB_ROLE:-app-readonly}"
PKI_ROLE="${PKI_ROLE:-vso-demo-app}"
SKIP_DATABASE="${SKIP_DATABASE:-false}"

export VAULT_ADDR VAULT_TOKEN
if [[ -n "${VAULT_NAMESPACE:-}" ]]; then
  export VAULT_NAMESPACE
fi

POLICY_DIR="$(cd "$(dirname "$0")" && pwd)/policies"

say() { printf "\n=== %s ===\n" "$*"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

require_cmd vault
require_cmd kubectl

say "Sanity check"
vault status >/dev/null || { echo "vault status failed" >&2; exit 1; }
echo "Vault reachable at ${VAULT_ADDR}"

# ----------------------------------------------------------------------
# Policy
# ----------------------------------------------------------------------
say "Writing policy ${POLICY_NAME}"
vault policy write "${POLICY_NAME}" "${POLICY_DIR}/vso-demo.hcl"

# ----------------------------------------------------------------------
# Kubernetes auth
# ----------------------------------------------------------------------
say "Configuring Kubernetes auth at path ${K8S_AUTH_PATH}"
if ! vault auth list -format=json | grep -q "\"${K8S_AUTH_PATH}/\""; then
  vault auth enable -path="${K8S_AUTH_PATH}" kubernetes
fi

if [[ -z "${K8S_API:-}" || -z "${K8S_CA_CERT_PATH:-}" ]]; then
  echo "K8S_API and K8S_CA_CERT_PATH are required to (re)configure Kubernetes auth." >&2
  echo "Set them and re-run, or pre-configure auth/${K8S_AUTH_PATH} manually." >&2
  exit 1
fi

vault write "auth/${K8S_AUTH_PATH}/config" \
  kubernetes_host="${K8S_API}" \
  kubernetes_ca_cert=@"${K8S_CA_CERT_PATH}" \
  disable_local_ca_jwt=false

say "Creating Vault role ${ROLE_NAME} bound to SA ${APP_NAMESPACE}/${APP_SA}"
vault write "auth/${K8S_AUTH_PATH}/role/${ROLE_NAME}" \
  bound_service_account_names="${APP_SA}" \
  bound_service_account_namespaces="${APP_NAMESPACE}" \
  policies="${POLICY_NAME}" \
  audience="vault" \
  ttl="1h"

# ----------------------------------------------------------------------
# KV v2 (Pattern 2)
# ----------------------------------------------------------------------
say "Enabling KV v2 at mount ${KV_MOUNT}"
if ! vault secrets list -format=json | grep -q "\"${KV_MOUNT}/\""; then
  vault secrets enable -path="${KV_MOUNT}" -version=2 kv
fi

say "Seeding ${KV_MOUNT}/vso-demo/static-config"
vault kv put "${KV_MOUNT}/vso-demo/static-config" \
  api_key="demo-key-$(date +%s)" \
  license_tier="premium" \
  feature_flag_x="true" \
  feature_flag_y="false" \
  last_updated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ----------------------------------------------------------------------
# PKI (Pattern 3)
# ----------------------------------------------------------------------
say "Enabling PKI at mount ${PKI_MOUNT}"
if ! vault secrets list -format=json | grep -q "\"${PKI_MOUNT}/\""; then
  vault secrets enable -path="${PKI_MOUNT}" pki
  vault secrets tune -max-lease-ttl=8760h "${PKI_MOUNT}"
fi

# Create a self-signed root inside the same mount if no issuer exists yet.
# In production you should sign this intermediate against an external root.
if ! vault read -format=json "${PKI_MOUNT}/issuers" 2>/dev/null | grep -q '"keys"'; then
  vault write -field=certificate "${PKI_MOUNT}/root/generate/internal" \
    common_name="vso-demo Root CA" \
    ttl=8760h >/dev/null
  vault write "${PKI_MOUNT}/config/urls" \
    issuing_certificates="${VAULT_ADDR}/v1/${PKI_MOUNT}/ca" \
    crl_distribution_points="${VAULT_ADDR}/v1/${PKI_MOUNT}/crl"
fi

say "Creating PKI role ${PKI_ROLE}"
vault write "${PKI_MOUNT}/roles/${PKI_ROLE}" \
  allowed_domains="demo.local,svc.cluster.local" \
  allow_subdomains=true \
  allow_bare_domains=true \
  max_ttl="1h" \
  ttl="5m" \
  key_type="rsa" \
  key_bits="2048"

# ----------------------------------------------------------------------
# Database (Pattern 1) — optional
# ----------------------------------------------------------------------
if [[ "${SKIP_DATABASE}" == "true" ]]; then
  echo
  echo "SKIP_DATABASE=true — leaving Pattern 1 unconfigured."
  echo "Delete the VaultDynamicSecret in manifests/04-vault-secrets.yaml to suppress related errors."
else
  : "${POSTGRES_CONN_URL:?POSTGRES_CONN_URL is required (set SKIP_DATABASE=true to opt out)}"
  : "${POSTGRES_ADMIN_USER:?POSTGRES_ADMIN_USER is required}"
  : "${POSTGRES_ADMIN_PASS:?POSTGRES_ADMIN_PASS is required}"

  say "Enabling Database engine at mount ${DB_MOUNT}"
  if ! vault secrets list -format=json | grep -q "\"${DB_MOUNT}/\""; then
    vault secrets enable -path="${DB_MOUNT}" database
  fi

  say "Configuring PostgreSQL connection"
  vault write "${DB_MOUNT}/config/postgres-demo" \
    plugin_name="postgresql-database-plugin" \
    allowed_roles="${DB_ROLE}" \
    connection_url="${POSTGRES_CONN_URL}" \
    username="${POSTGRES_ADMIN_USER}" \
    password="${POSTGRES_ADMIN_PASS}"

  say "Creating database role ${DB_ROLE} (TTL 90s, max 2m)"
  vault write "${DB_MOUNT}/roles/${DB_ROLE}" \
    db_name="postgres-demo" \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT pg_read_all_data TO \"{{name}}\";" \
    revocation_statements="REVOKE pg_read_all_data FROM \"{{name}}\"; DROP ROLE IF EXISTS \"{{name}}\";" \
    default_ttl="90s" \
    max_ttl="2m"
fi

say "Done"
cat <<EOF

Next steps:
  1) Update manifests/02-vault-connection.yaml with your Vault address.
  2) Update manifests/03-vault-auth.yaml with your auth mount path (default: ${K8S_AUTH_PATH}).
  3) Apply the manifests:
        kubectl apply -f ../manifests/
  4) Port-forward and open the UI:
        kubectl port-forward -n ${APP_NAMESPACE} svc/vso-demo-app 8080:8080
        open http://localhost:8080
EOF
