# Apps Overview

Apps deployed across k3s and Mac Mini.

| App | Host | URL | Purpose |
|-----|------|-----|---------|
| Ecdysis | k3s | `ecdysis.amer.dev` / `ecdysis-uat.amer.dev` | Moltbook agent management dashboard |
| LLM Manager | k3s | `llm-manager.amer.dev` (UI, Tailscale-only) / `llm-manager-backend.amer.dev` (API) | GPU resource manager + inference queue |
| Mycroft | k3s | `mycroft.amer.dev/debug` | AI agent platform (coordinator + Argo Workflows) |
| Home Assistant | Mac Mini | `ha.amer.dev` | Home automation |
| Vikunja | k3s | `todo.amer.dev` | Self-hosted todo / project management |
| Sazed | k3s | `reports.amer.dev` / `sazed.amer.dev` | AI research reports viewer |
| Wiki | k3s | `wiki.amer.dev` | This wiki |

## Shared Infrastructure

All k3s apps share:

- **Secrets:** BWS → ExternalSecret → `<app>-credentials` k8s Secret
- **Ingress:** Traefik → `*.amer.dev` (cert-manager wildcard TLS)
- **Deployment:** GitOps via ArgoCD watching `k3s-dean-gitops` — see [GitOps Pipeline](../infra/gitops.md)
- **LLM inference:** via LLM Manager queue (never call Ollama directly)
