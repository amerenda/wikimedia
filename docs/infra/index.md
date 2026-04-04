# Infrastructure Overview

| Component | Details |
|-----------|---------|
| **k3s cluster** | 3x RPi controllers (etcd on tmpfs), worker nodes |
| **Mac Mini M4** | Docker Compose — core services, databases, AI |
| **GitOps** | ArgoCD + `k3s-dean-gitops` |
| **Secrets** | BWS + External Secrets Operator |
| **Storage** | Longhorn — rpi5-1 NVMe (2TB), RAID 5 on murderbot planned |

See individual pages for details.
