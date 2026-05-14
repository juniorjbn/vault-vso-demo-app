# Architecture

This demo packs three independent secret-rotation patterns into the same pod.
The pod itself never restarts during normal operation; rotation happens through
filesystem updates that the application re-reads on each request.

## Component overview

```mermaid
flowchart LR
    classDef vault fill:#FFCD58,stroke:#A37A00,color:#1f2937
    classDef k8s fill:#326CE5,stroke:#1e3a8a,color:#ffffff
    classDef app fill:#22c55e,stroke:#15803d,color:#0f172a
    classDef store fill:#1e293b,stroke:#475569,color:#e2e8f0

    V[HashiCorp Vault Enterprise]:::vault
    VSO[Vault Secrets Operator]:::k8s

    subgraph NS["namespace: vso-demo"]
      direction TB
      SA[ServiceAccount<br/>vso-demo-app]:::k8s
      DS[(Secret<br/>db-creds)]:::store
      SS[(Secret<br/>vso-demo-static-config)]:::store
      PS[(Secret<br/>vso-demo-pki-cert)]:::store

      subgraph POD["Pod: vso-demo-app"]
        direction TB
        SIDE[sidecar<br/>kubectl poll 3s]:::app
        APP[webapp<br/>Flask]:::app
        VOL[/shared volume<br/>emptyDir/]:::store
        MNT_S[/static-config<br/>mount/]:::store
        MNT_P[/tls<br/>mount/]:::store
      end
    end

    V -- "kubernetes auth<br/>role: vso-demo" --> VSO
    VSO -- "VaultDynamicSecret" --> DS
    VSO -- "VaultStaticSecret" --> SS
    VSO -- "VaultPKISecret" --> PS

    DS -. polled .-> SIDE
    SIDE -- writes --> VOL
    VOL -- read each request --> APP
    SS -. mounted .-> MNT_S
    PS -. mounted .-> MNT_P
    MNT_S -- read each request --> APP
    MNT_P -- read each request --> APP
```

## The three patterns

### Pattern 1 — Dynamic Secret (Database)

```mermaid
sequenceDiagram
    participant V as Vault
    participant VSO as VSO
    participant K as K8s Secret<br/>db-creds
    participant S as Sidecar
    participant A as Webapp
    Note over V,A: Initial issuance
    VSO->>V: read database/creds/app-readonly
    V-->>VSO: { username, password, lease 90s }
    VSO->>K: create/update db-creds
    loop every 3s
      S->>K: GET secret db-creds
      K-->>S: latest values
      S->>S: write /shared/credentials.txt
    end
    A->>A: re-read /shared/credentials.txt on each request
    Note over V,A: At ~67% of lease lifetime
    VSO->>V: renew lease (or request new one)
    V-->>VSO: new credentials
    VSO->>K: overwrite db-creds
    Note right of A: pod NEVER restarts
```

Why the sidecar? Without `rolloutRestartTargets` on the `VaultDynamicSecret`,
the K8s Secret updates in place but the pod has no native way to know. The
sidecar bridges that gap by polling the API and writing to a shared volume.

### Pattern 2 — Static Secret (KV v2)

```mermaid
sequenceDiagram
    participant V as Vault
    participant VSO as VSO
    participant K as K8s Secret<br/>vso-demo-static-config
    participant A as Webapp
    loop every refreshAfter (30s)
      VSO->>V: read demo/data/vso-demo/static-config
      V-->>VSO: current KV payload
      VSO->>K: overwrite Secret if changed
    end
    Note over K,A: Secret mounted as a volume at /static-config
    A->>A: re-read /static-config/* on each request
    Note over A: kubelet propagates Secret updates<br/>within its sync interval (~60s)
```

No sidecar needed — kubelet handles the in-place update of mounted Secrets.

### Pattern 3 — PKI Secret

```mermaid
sequenceDiagram
    participant V as Vault
    participant VSO as VSO
    participant K as K8s Secret<br/>vso-demo-pki-cert (tls)
    participant A as Webapp
    Note over V,A: Initial issuance
    VSO->>V: pki-int/issue/vso-demo-app (TTL 5m)
    V-->>VSO: cert + key + chain
    VSO->>K: create K8s tls Secret
    Note over V,A: When remaining lifetime < expiryOffset (2m)
    VSO->>V: pki-int/issue/vso-demo-app (TTL 5m)
    V-->>VSO: new cert + key
    VSO->>K: overwrite K8s Secret
    Note over K,A: Secret mounted at /tls/{tls.crt,tls.key}
    A->>A: re-parse cert on each request
```

Same as Pattern 2 from a delivery angle: the cert lives in a K8s Secret that
kubelet keeps in sync with the volume mount. The novelty is the rotation
trigger (`expiryOffset`) and the TLS-typed Secret.

## Why "no restart" matters

Long-lived processes with in-memory connection pools, JIT-compiled caches, or
expensive startup costs benefit a lot from never being recycled by a secret
rotation event. The trade-off:

- Webapp must re-read its inputs from disk often enough (every request is fine
  for low-traffic UIs, periodic refresh threads are needed for high-RPS apps).
- Database drivers must reconnect when credentials rotate. The simplest way is
  to set a short max age on the connection pool (e.g., 60s) so workers naturally
  pick up the new credentials. The sidecar approach assumes this.

For workloads that don't mind a restart, VSO's `rolloutRestartTargets` is
simpler and has lower memory cost (no sidecar).
