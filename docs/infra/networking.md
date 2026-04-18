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

### Architecture

```
Client (LAN / Tailscale)
    │
    │  DNS query to 10.100.20.240:53
    ▼
 pf redirect (macOS)
    │  10.100.20.240:53 → :15354
    ▼
 dns-udp-proxy.py (en0-bound)
    │  forwards to OrbStack VM
    ▼
 Technitium DNS (container, network_mode: host)
    │  port 5354 inside OrbStack VM
    │
    ├── Local zones (*.amer.dev) → authoritative answers
    ├── Advanced Blocking app → per-client filtering
    └── Upstream recursive → Cloudflare / Google
```

### Technitium DNS

- **Host:** Mac Mini M4, Docker container via OrbStack
- **Public IP:** `10.100.20.240` (IP alias on `en0`, managed by `pf-dns-redirect.sh` LaunchDaemon)
- **Internal port:** `5354` (OrbStack intercepts 53/5353/5354 on the host, so pf + a userspace proxy bridge the gap)
- **Admin UI:** `http://10.100.20.240:5380`
- **Domain:** `*.amer.dev` — all internal services resolve here
- **Previously:** Pi-hole + BIND9 on k3s (migrated to Technitium for unified management)

### DNS Proxy Chain

OrbStack on macOS intercepts ports 53, 5353, and 5354, so a userspace proxy is required to bridge DNS traffic into the OrbStack VM:

| Component | Location | Purpose |
|-----------|----------|---------|
| `pf-dns-redirect.sh` | macOS LaunchDaemon | Adds IP alias `10.100.20.240` on `en0`, redirects `:53` → `:15354` via pf rules |
| `dns-udp-proxy.py` | macOS LaunchDaemon | UDP+TCP proxy bound to `en0` (via `IP_BOUND_IF`), forwards to OrbStack VM at `192.168.139.2:5354` |
| Technitium | OrbStack container | Listens on `5354`, `network_mode: host` |

**Known limitation:** The proxy rewrites the source IP — Technitium sees all queries as coming from `192.168.139.3` (the Mac Mini's OrbStack bridge IP), not the real client. This means per-client features like Advanced Blocking's `networkGroupMap` only distinguish clients that query Technitium directly (not through the proxy).

### External DNS (DigitalOcean)

Public DNS records are managed automatically by the **External DNS** operator on k3s:

- Watches Ingress resources for `external-dns.alpha.kubernetes.io/hostname` annotations
- Creates/updates DNS records on DigitalOcean
- TTL controlled per-ingress via annotation

### School Mode (Distraction Blocker)

School Mode is a custom app that manages DNS-based blocking via Technitium's **Advanced Blocking** app.

| Component | Location | Purpose |
|-----------|----------|---------|
| **School Mode app** | k3s (`schoolmode` namespace) | Web UI + API to toggle blocking per device |
| **Advanced Blocking** | Technitium DNS app | Per-client DNS blocking with configurable blocklists |
| **Block page** | k3s (`block-page` namespace) | Static nginx site showing a custom image for blocked requests |

**How it works:**

1. Admin opens `schoolmode.amer.dev` and toggles blocking for a device IP
2. School Mode app updates Technitium's Advanced Blocking config via API
3. Blocked domains resolve to `10.100.20.205` (block page LoadBalancer IP)
4. Technitium's DNS cache is flushed so the change takes effect immediately
5. `blockingAnswerTtl` is set to 5 seconds so clients pick up changes fast

**Blocklists** (social media — Facebook, Instagram, TikTok, YouTube, Reddit, Snapchat, Twitter/X, Twitch, Netflix, Discord, Pinterest):

All sourced from [gieljnssns/Social-media-Blocklists](https://github.com/gieljnssns/Social-media-Blocklists) in Pi-hole format.

**Timer support:** Blocking can be set with a timer (15m, 30m, 1h, 2h, 4h) — auto-unblocks when the timer expires.

**Repos:**

- App: `amerenda/schoolmode`
- Blocklist config: managed by School Mode via Technitium API
- Block page: `k3s-dean-gitops/apps/block-page/`

**Credentials:** Technitium user `blocklist` (DNS Administrator group), password in BWS as `blocklist-dean-password`.

## Ingress & TLS

- **Ingress controller:** Traefik on k3s — routes all `*.amer.dev` traffic to services
- **TLS:** cert-manager with DNS-01 challenge for wildcard `*.amer.dev` cert
- **External exposure:** select services exposed publicly; most are internal-only

## Tailscale

### Overview

Remote access to the homelab from outside the LAN. Two k3s pods act as subnet routers and exit nodes.

### Deployment

| Component | Location | Purpose |
|-----------|----------|---------|
| Tailscale pods (x2) | k3s `default` namespace | Subnet router (`10.100.20.0/24`) + exit node |
| ACL policy | `amerenda/tailscale-acl` repo | Access control, pushed via CI on merge |
| Auth key | BWS → ExternalSecret `tailscale-auth-key` | Ephemeral auth for pod registration |

### Subnet Routing

- Pods advertise `10.100.20.0/24` so remote Tailscale clients can reach LAN services
- `--advertise-exit-node` enabled — clients can route all traffic through the homelab
- IP forwarding enabled (`net.ipv4.ip_forward=1`)
- Pods run privileged with `NET_ADMIN` and `SYS_MODULE` capabilities
- Pod anti-affinity spreads replicas across nodes

### ACL Policy

Managed in `amerenda/tailscale-acl/policy.hujson`. CI auto-applies on push to main.

| Source | Destination | Notes |
|--------|------------|-------|
| `amerenda@github` | `*:*` | Full access (Alex) |
| `tag:inner-sanctum` | `*:*` | Full access (infra devices) |
| `tag:guest` / `group:guests` | `tag:subnet-router:3002` | Guest app access |
| `tag:guest` / `group:guests` | `10.100.20.0/24` ports 53,80,443,3000-3001,8080,8443,8888,9000,9090 | Guest LAN access (DNS + web services) |

**Guest group:** `eafalck@gmail.com`

### MASQUERADE

The tailscale pods MASQUERADE all subnet-routed traffic (`ts-postrouting` chain, mark `0x40000/0xff0000`). This means services on the LAN (like Technitium) see the pod's IP as the source, not the client's Tailscale IP.

This is required for exit node routing — removing MASQUERADE breaks return path routing for devices using the pod as an exit node.

### DNS

Tailscale pods use `dnsPolicy: None` with `nameservers: [10.100.20.240]` (Technitium). However, `TS_ACCEPT_DNS=true` causes tailscaled to overwrite `/etc/resolv.conf` with MagicDNS (`100.100.100.100`).

## Security

- Camera traffic blocked at router/firewall level (no cloud egress for cameras)
- IoT devices isolated (VLAN or firewall rules — _TODO: document_)
- Komodo manages secrets on Mac Mini via `/etc/komodo/` (not in k3s secrets)

## Services & Ports

| Service | Host | Port | URL | Access |
|---------|------|------|-----|--------|
| k3s API | 10.100.20.10-12 | 6443 | — | Internal |
| Traefik | k3s (LoadBalancer) | 80/443 | `10.100.20.203` | Public (select) |
| Technitium DNS | Mac Mini | 53 (alias: `10.100.20.240`) | `http://10.100.20.240:5380` | LAN |
| Block page | k3s (LoadBalancer) | 80 | `10.100.20.205` | LAN |
| Home Assistant | Mac Mini | 8123 | `ha.amer.dev` | Tailscale |
| ArgoCD | k3s | — | `argocd.amer.dev` | Tailscale |
| Ecdysis | k3s | — | `ecdysis.amer.dev` | Tailscale |
| LLM Manager | k3s | — | `llm-manager.amer.dev` | Tailscale |
| School Mode | k3s | — | `schoolmode.amer.dev` | Tailscale |
| Wiki | k3s | — | `wiki.amer.dev` | Public |
| Mycroft | k3s | — | `mycroft.amer.dev` | Tailscale |
| Komodo | Mac Mini | — | `komodo.amer.dev` | Tailscale |
