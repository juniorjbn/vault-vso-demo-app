#!/usr/bin/env bash
# Credential-monitor sidecar.
#
# Polls the K8s Secret `db-creds` (kept in sync with Vault by VSO) and writes
# the current values to /shared/credentials.txt. The Flask container re-reads
# that file on every HTTP request, so credential rotation happens without a
# pod restart.
#
# Inputs:
#   NAMESPACE   - the namespace the pod runs in (defaulted by the Deployment).
#   POLL_SECONDS - how often to refresh from the API (default: 3).
set -euo pipefail

NAMESPACE="${NAMESPACE:-vso-demo}"
POLL_SECONDS="${POLL_SECONDS:-3}"

echo "[sidecar] starting credential monitor (namespace=${NAMESPACE}, poll=${POLL_SECONDS}s)"

while true; do
  U=$(kubectl get secret db-creds -n "${NAMESPACE}" -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || true)
  P=$(kubectl get secret db-creds -n "${NAMESPACE}" -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)
  TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  if [ -n "${U}" ] && [ -n "${P}" ]; then
    cat > /shared/credentials.txt <<EOF
username=${U}
password=${P}
updated=${TS}
EOF
    echo "[sidecar ${TS}] credentials refreshed: user=${U}"
  else
    echo "[sidecar ${TS}] waiting for secret db-creds..."
  fi
  sleep "${POLL_SECONDS}"
done
