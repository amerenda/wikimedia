# Homelab Wiki

Internal documentation for the `amer.dev` homelab — apps, infrastructure, and runbooks.

## Quick Links

| Section | Description |
|---------|-------------|
| [Infrastructure](infra/index.md) | k3s cluster, Mac Mini, networking, storage |
| [Apps](apps/index.md) | Deployed applications and services |
| [Runbooks](runbooks/index.md) | Step-by-step operational guides |

## Stack at a Glance

- **k3s cluster**: 3x RPi controllers (etcd), worker nodes including murderbot
- **Mac Mini M4**: Docker Compose services — Postgres, Home Assistant, voice pipeline, Ollama, Komodo
- **GitOps**: ArgoCD + `k3s-dean-gitops`, deploy-bot CI
- **Secrets**: Bitwarden Secrets Manager (BWS) + External Secrets Operator
- **DNS/TLS**: Traefik ingress, cert-manager, `*.amer.dev`
