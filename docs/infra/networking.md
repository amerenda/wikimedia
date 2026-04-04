# Networking

## Network Map

```
Internet
    │
    │ (ISP)
    ▼
 Router / Firewall
    │
    ├── LAN (10.100.20.x)
    │       ├── rpi5-0   10.100.20.10  k3s controller
    │       ├── rpi5-1   10.100.20.11  k3s controller + storage
    │       ├── rpi4-0   10.100.20.12  k3s controller
    │       ├── murderbot             k3s worker (amd64)
    │       └── Mac Mini M4           Docker Compose services
    │
    └── Tailscale overlay (*.amer.dev remote access)

_TODO: add IoT/camera subnet/VLAN details, router model, external IP handling_
```

## DNS

- **Resolver:** Technitium DNS on Mac Mini
- **Domain:** `*.amer.dev` — all internal services resolve via Technitium
- **External DNS:** handled at registrar; public-facing records point to external IP
- **Previously:** Pi-hole (migrated to Technitium for split-horizon and better management)

_TODO: document split-horizon config, upstream resolvers, any AdBlock lists still active_

## Ingress & TLS

- **Ingress controller:** Traefik on k3s — routes all `*.amer.dev` traffic to services
- **TLS:** cert-manager with DNS-01 challenge for wildcard `*.amer.dev` cert
- **External exposure:** select services exposed publicly; most are internal-only

## Tailscale

- Used for remote access to the homelab from outside the LAN
- ACL policy managed as code in `amerenda/tailscale-acl` repo
- CI auto-applies ACL changes on push to main

_TODO: document exit node setup, subnet routing config_

## Security

- Camera traffic blocked at router/firewall level (no cloud egress for cameras)
- IoT devices isolated (VLAN or firewall rules — _TODO: document_)
- Komodo manages secrets on Mac Mini via `/etc/komodo/` (not in k3s secrets)

## Services & Ports

| Service | Host | Port | Exposure |
|---------|------|------|----------|
| k3s API | 10.100.20.10-12 | 6443 | Internal |
| Traefik | k3s | 80/443 | Public (select) |
| Technitium DNS | Mac Mini | 53 | LAN |
| Home Assistant | Mac Mini | — | `ha.amer.dev` |
| ArgoCD | k3s | — | `argocd.amer.dev` |
| Ecdysis | k3s | — | `ecdysis.amer.dev` |
| LLM Manager | k3s | — | `llm-manager.amer.dev` |
| Wiki | k3s | — | `wiki.amer.dev` |
| Mycroft debug | k3s | — | `mycroft.amer.dev/debug` |
| Komodo | Mac Mini | — | `komodo.amer.dev` |

_TODO: add full service inventory with internal cluster IPs and Mac Mini ports_
