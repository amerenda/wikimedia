# k3s Cluster

## Nodes

| Node | Role | Hardware | IP |
|------|------|----------|----|
| rpi5-0 | controller | RPi 5 | 10.100.20.10 |
| rpi5-1 | controller + storage | RPi 5, NVMe 2TB | 10.100.20.11 |
| rpi4-0 | controller | RPi 4 | 10.100.20.12 |
| murderbot | worker | x86, 2x 8TB drives | — |

## etcd

- Runs on **tmpfs (1GB)** on all 3 controllers — eliminates SD card I/O and wear
- **Staggered snapshots:** each controller offsets by node index (~100s apart) to avoid simultaneous snapshot I/O
- **Auto-recovery service** (`k3s-etcd-recovery.service`) detects and removes stale etcd members on restart
- Snapshot backups offloaded to GCS via Longhorn (not etcd snapshots directly — see Storage)

## GitOps (ArgoCD)

See the [GitOps page](gitops.md) for full pipeline details.

- ArgoCD watches `k3s-dean-gitops` `main` branch
- Root App-of-Apps pattern: one root application manages all infra + app ArgoCD Applications
- **UAT-first deploy:** UAT manifests committed directly to main (auto-synced), prod changes go through human-reviewed PR
- `deploy-bot` identity pushes image tag updates

## Secrets

```
Bitwarden Secrets Manager (BWS)
    └── External Secrets Operator (ClusterSecretStore: bitwarden-secretstore)
            └── ExternalSecret (per namespace)
                    └── k8s Secret → pod env vars / volume mounts
```

ExternalSecrets refresh every 1h. One `ExternalSecret` manifest per app namespace. All reference the same `ClusterSecretStore`.

## Infrastructure Stack

Sync waves control deployment order (lower = earlier):

| Wave | Component | Purpose |
|------|-----------|---------|
| 0 | flannel | CNI networking |
| 0 | metallb | Load balancer |
| 0 | cert-manager | TLS cert management (ACME / Let's Encrypt) |
| 1 | traefik | Ingress controller → `*.amer.dev` |
| 1 | arc-controller | GitHub Actions Runner Controller |
| 2 | external-secrets | BWS secret sync (needs cert-manager TLS) |
| 3 | longhorn | Distributed storage with GCS backups |
| 4 | external-dns | Auto-manage DNS records (DigitalOcean) |
| 5 | argo-workflows | Workflow engine (Mycroft agent tasks) |
| 5 | monitoring | Prometheus + Grafana + node-exporter |
| 5 | tailscale | VPN access |
| 5 | reloader | Auto-restart pods on ConfigMap/Secret changes |
| 5 | apps | All application workloads |
| 20 | cert-manager-external | Production Let's Encrypt issuer |
| 21 | ingresses | Cluster-level ingress definitions |

## Storage (Longhorn)

- **Storage node:** rpi5-1 NVMe 2TB
- `defaultReplicaCount: 1` — single replica per volume
- Other nodes (`rpi4-0`, `rpi5-0`, `murderbot`): scheduling disabled pending RAID 5
- **Backups:** GCS bucket, daily at 2am, 7-day retention

**Planned — murderbot RAID 5:**
- 4× 8TB → mdadm RAID 5 (~24TB usable)
- Mount at `/var/lib/longhorn-murderbot`
- After setup: add as storage node, bump replicas to 2

## Monitoring

- **Grafana:** `grafana.amer.home`
- **Stack:** kube-prometheus-stack (Prometheus + Grafana + node-exporter) — Helm v82.1.0
- **Retention:** 7 days, 10Gi PVC

## Useful Commands

```bash
# Check cluster nodes
kubectl get nodes -o wide

# ArgoCD app status
kubectl get applications -n argocd

# Check sync waves in progress
kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}: {.status.sync.status}{"\n"}{end}'

# Force-sync an app
argocd app sync <app-name>

# Longhorn status
kubectl get volumes -n longhorn-system

# etcd member health
kubectl -n kube-system exec etcd-rpi5-0 -- etcdctl member list
```
