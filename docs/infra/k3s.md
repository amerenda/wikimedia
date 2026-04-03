# k3s Cluster

## Nodes

| Node | Role | Hardware |
|------|------|----------|
| rpi5-0 | controller | RPi 5 |
| rpi5-1 | controller + storage | RPi 5, NVMe 256GB |
| rpi4-0 | controller | RPi 4 |
| murderbot | worker | x86, 2x 8TB drives |

## etcd

- Runs on tmpfs (1GB) on all 3 controllers — eliminates SD card I/O
- Staggered snapshots: each controller offsets by index (~100s apart)
- Auto-recovery service (`k3s-etcd-recovery.service`) handles stale members on restart

## GitOps

- ArgoCD watches `k3s-dean-gitops` main branch
- ApplicationSet generates an Application per app directory
- deploy-bot identity pushes image tag updates via PRs
- Label filtering: PRs tagged `deploy` are auto-merged by CI

## Secrets

- External Secrets Operator (ESO) pulls from BWS
- `ClusterSecretStore` authenticates with BWS access token
- One `ExternalSecret` per app namespace
