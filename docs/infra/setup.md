# Cluster Setup & Ansible

Infrastructure-as-code for provisioning the k3s cluster, RPi nodes, GPU hosts, and Mac Mini. All playbooks live in `amerenda/ansible-playbooks`.

## Inventory

```
controllers   rpi5-0 (10.100.20.10)  — k3s controller, cluster-init
              rpi5-1 (10.100.20.11)  — k3s controller, preferred restore leader, NVMe 2TB
              rpi4-0 (10.100.20.12)  — k3s controller, 4GB RAM

agents        rpi3-0 (10.100.20.13)  — storage-only agent (927MB RAM — no regular pods)

gpu_hosts     murderbot (10.100.20.19) — x86, NVIDIA GPU, Docker Compose
              archlinux (10.100.20.25) — AMD GPU, Docker Compose (optional)

macmini_hosts mac-mini-m4 (10.100.20.18) — OrbStack, HA, Ollama, Komodo

Gateway: 10.100.20.1  |  All nodes: user alex, SSH key ~/.ssh/alex_id_ed25519
```

## Playbooks

### Full cluster from scratch
```bash
ansible-playbook -i inventory/inventory.ini all.yml -e bws_access_token=<TOKEN>
```
Runs in sequence: fetch-secrets → setup-rpi → k3s-controller → k3s-agent → longhorn-storage → post-k3s → etcd-tmpfs → k3s-recover → post-k3s-setup (ArgoCD) → smoke-test

### Individual playbooks

| Playbook | What it does | Safety |
|----------|-------------|--------|
| `setup-rpi.yml` | Static IP, DNS, base packages, cgroup config | Non-disruptive |
| `k3s-controller.yml` | Install k3s + etcd HA, fetch kubeconfig | `serial: [1, n-1]` + health gate |
| `k3s-agent.yml` | Join worker nodes to cluster | `serial: 1` + health gate |
| `longhorn-storage.yml` | iSCSI/NFS prereqs, Longhorn node scheduling | Non-disruptive |
| `post-k3s.yml` | Node labels (`longhorn-storage=true`) + taints | Non-disruptive |
| `etcd-tmpfs.yml` | Migrate etcd to 1GB RAM disk | `serial: 1` + confirmation + snapshot first |
| `nvme-setup.yml` | PCIe Gen 2, format + mount NVMe (RPi 5 only) | Reboots if config changed |
| `k3s-recover.yml` | Fix config/tmpfs, deploy auto-recovery service, optional token rotation | `serial: 1` + confirmation for destructive ops |
| `k3s-full-recovery.yml` | Break-glass: restore all controllers from snapshot | Confirmation required |
| `enable-etcd-metrics.yml` | Enable etcd Prometheus metrics | `serial: 1` + health gate |
| `docker-storage.yml` | Move Docker data root to `/mnt/storage` (GPU hosts) | GPU hosts only |
| `setup-macmini.yml` | Homebrew, OrbStack, Ollama, Komodo, Tailscale, BlueBubbles | Mac Mini only |
| `smoke-test.yml` | Validate nodes, etcd, tmpfs, snapshots, Longhorn, ArgoCD | Read-only, safe anytime |
| `post-k3s-setup.yml` | Install ArgoCD, create repo secret, apply root-app | Run after k3s is healthy |

**Common flags:**
```bash
# Limit to specific nodes
--limit rpi5-1

# Run only certain tag groups
--tags "k3s,longhorn"

# Available tags: bootstrap, k3s, longhorn, etcd, nvme, recover, argocd,
#   smoke-test, macmini (+ subtags: mini-homebrew, mini-ollama, mini-komodo,
#   mini-secrets, mini-tailscale, mini-bluebubbles, mini-dns)
```

## Secrets (BWS)

All secrets come from Bitwarden Secrets Manager. Pass `bws_access_token` at runtime — the playbook fetches everything automatically:

```bash
ansible-playbook ... -e bws_access_token=<TOKEN>
```

| BWS secret key | Used by |
|---|---|
| `k3s-dean-etcd-token` | k3s cluster join token (all nodes) |
| `github-pat-k3s-dean-gitops` | ArgoCD repo access + CI |
| `docker-hub-k3s-runner-api-key` | Docker Hub credentials |
| `komodo-dean-*` (5 secrets) | Komodo on Mac Mini |
| `github-app-arc-id/private-key` | GitHub App for runners |

## etcd on tmpfs

etcd runs on a 1GB RAM disk on all controllers — eliminates SD card I/O and extends card lifespan.

**Trade-off:** etcd data is wiped on every reboot. Recovery relies on snapshots.

**Snapshot schedule:**
- Every 5 minutes, 12 retained
- Controllers stagger by index: rpi5-0 at `:00`, rpi5-1 at `:01`, rpi4-0 at `:02`
- A snapshot exists somewhere roughly every ~100 seconds

**Auto-recovery service** (`k3s-etcd-recovery.service`) — deployed by `k3s-recover.yml`:

| Scenario | Behavior |
|----------|----------|
| Single node reboot, peers up | Detects peers, wipes local etcd, rejoins as follower |
| Full cluster power loss | Waits up to 3 min for peers; node with freshest snapshot restores and leads |

**Restore priority:** rpi5-1 → rpi5-0 → rpi4-0 (by inventory index + snapshot freshness)  
**Max data loss window:** 5 minutes (snapshot interval)

## Safety Mechanisms

Every playbook that touches live nodes includes:

- **Pre-flight gate** (`check-cluster-health.yml`) — aborts if any node is NotReady
- **Post-flight gate** (`wait-for-node-ready.yml`) — waits for node to rejoin before proceeding
- **Serial execution** — `serial: 1` or `serial: [1, n-1]` — never touches two nodes simultaneously
- **Confirmation prompt** (`confirm-destructive.yml`) — required for etcd migration and recovery ops
- **3-controller quorum** — tolerate 1 node down; health gate prevents touching a second while first recovers

## RPi 5 NVMe Setup

Handled by `nvme-setup.yml`. Enables PCIe Gen 2 on the RPi 5 HAT+, formats `/dev/nvme0n1` as ext4, and mounts at `/var/lib/longhorn-nvme`. The playbook reboots the node if the PCIe config changed.

## Mac Mini Setup

`setup-macmini.yml` installs and configures:

- **Homebrew** — CLI tools (git, jq, htop, kubectl, socat)
- **OrbStack** — Docker runtime
- **Ollama** — LLM inference (native, uses M4 Metal GPU)
- **Komodo** — GitOps for Docker Compose (watches `mac-mini-compose` repo)
- **Tailscale** — VPN
- **BlueBubbles** — iMessage proxy (optional)

Prerequisites for a fresh Mac Mini (run manually once):
```bash
bash mac-mini-init.sh   # Installs Xcode CLI Tools + Rosetta
```
