# GitOps — k3s Deploy Pipeline

All k3s infrastructure and applications are managed via GitOps using ArgoCD watching the `amerenda/k3s-dean-gitops` repo.

## Repository Layout

```
k3s-dean-gitops/
├── root-app.yaml              # App-of-Apps root (apply this to bootstrap)
├── bootstrap/                 # One-time manual setup (secrets, AppProjects)
├── infra/                     # Infrastructure components (ArgoCD Applications)
│   ├── argocd-config/         # ArgoCD settings + UAT ApplicationSet
│   ├── traefik/               # Ingress controller
│   ├── cert-manager/          # TLS certs
│   ├── external-secrets/      # BWS secret sync
│   ├── longhorn/              # Distributed storage
│   ├── metallb/               # Load balancer
│   ├── monitoring/            # Prometheus + Grafana
│   ├── argo-workflows/        # Workflow engine
│   ├── tailscale/             # VPN
│   ├── arc-controller/        # GitHub Actions Runner Controller
│   ├── arc-runners-*/         # Per-repo ARC runner scale sets
│   └── ingresses/             # Cluster-level ingress definitions
└── apps/                      # Application workloads
    ├── ecdysis/
    ├── llm-manager/
    ├── mycroft/
    ├── vikunja/
    ├── wikimedia/
    ├── pihole/
    ├── unifi-network-application/
    └── home-assistant/        # Config only — HA runs on Mac Mini
```

## Deploy Pipeline

### App Repos → k3s-dean-gitops

```
Push to app repo main
    │
    ▼
CI: test → build images (amd64 + arm64) → push to Docker Hub
    │
    ├── Commit UAT manifest changes directly to k3s-dean-gitops main
    │       └── ArgoCD auto-syncs UAT environment ✓
    │
    └── Open prod deploy PR on branch deploy/<app>-<tag>
            └── Human reviews + merges
                    └── ArgoCD syncs prod ✓
```

### Manifest Conventions

| Path | Environment | Sync trigger |
|------|-------------|--------------|
| `apps/<app>/<component>/` | **Prod** | PR merge (human approval) |
| `apps/<app>/<component>-uat/` | **UAT** | Direct commit to main (auto) |

### PR Labels

CI labels deploy PRs with `deploy:<app>` (e.g., `deploy:mycroft`). The UAT ApplicationSet uses these labels to create ephemeral UAT ArgoCD Applications from the PR branch.

When the PR is merged or closed, the UAT app is automatically deleted.

### Git Identity

All CI commits use:
```
name:  amerenda-deploy-bot[bot]
email: 3192609+amerenda-deploy-bot[bot]@users.noreply.github.com
```

## UAT ApplicationSet

Located at `infra/argocd-config/uat-applicationset.yaml`.

Uses a **matrix generator**: Pull Request (labeled `deploy:<app>`) × List (app/path combos). Creates ArgoCD Applications named `uat-<app>-pr<number>`, syncing from the PR branch.

**Supported apps:** ecdysis, llm-manager, mycroft

## Apps Inventory

| App | Namespace | UAT | Notes |
|-----|-----------|-----|-------|
| ecdysis | ecdysis | ✓ | Frontend + backend, reset job available |
| llm-manager | llm-manager | ✓ | Frontend + backend |
| mycroft | mycroft | ✓ | Coordinator + Argo Workflow templates |
| vikunja | vikunja | — | Todo app + Redis + Grafana dashboard |
| wikimedia | wikimedia | — | Tailscale-protected access |
| pihole | pihole | — | Helm-based |
| unifi | unifi | — | MongoDB + UniFi controller |
| home-assistant | home-assistant | — | Config/PVC only — runs on Mac Mini |

## Bootstrap (New Cluster)

These steps require manual `kubectl apply` — ArgoCD isn't running yet:

```bash
# 1. Install ArgoCD via Helm (values in bootstrap/argocd/values.yaml)
helm install argocd argo/argo-cd -n argocd -f bootstrap/argocd/values.yaml

# 2. Apply GitHub PAT for repo access
kubectl apply -f bootstrap/argocd-repo-secret.yaml   # update PAT first

# 3. Apply AppProjects (required before apps can sync)
kubectl apply -f bootstrap/appprojects.yaml

# 4. Apply BWS credentials for ExternalSecrets
kubectl apply -f bootstrap/bitwarden-credentials-secret.yaml   # update token first

# 5. Apply the root App-of-Apps — ArgoCD takes over from here
kubectl apply -f root-app.yaml
```

ArgoCD will then deploy all infra and apps in sync-wave order automatically.

## Sync Waves

Waves enforce deployment ordering. Infra must be ready before apps:

```
Wave 0  → Networking (flannel, metallb, cert-manager)
Wave 1  → Ingress (traefik), ARC controller
Wave 2  → External secrets (needs cert-manager for webhook TLS)
Wave 3  → Storage (longhorn, needs secrets for GCS)
Wave 4  → DNS (external-dns)
Wave 5  → Everything else (apps, monitoring, tailscale, runners)
Wave 20 → External cert issuer (after cert-manager is stable)
Wave 21 → Cluster ingress definitions
```

## Adding a New App

1. Create `apps/<app>/` directory with deployment, service, ingress, externalsecret manifests
2. For UAT: add `apps/<app>/<component>-uat/` with UAT-specific overrides
3. Add `apps/<app>/<component>-uat` to the UAT ApplicationSet matrix (if UAT wanted)
4. Add a new ArgoCD Application block in `root-app.yaml`
5. Add `deploy:<app>` label handling in the app repo's CI workflow

See [Runners](runners.md) if the app also needs its own CI runner.
