# Mac Mini M4

Core services host. Managed via `amerenda/mac-mini-compose` (Docker Compose) + Komodo GitOps.

**Repo:** [`amerenda/mac-mini-compose`](https://github.com/amerenda/mac-mini-compose)

## Services

### Services stack (`docker-compose.yaml`)

| Service | Network | Port | Purpose |
|---------|---------|------|---------|
| Home Assistant | host | 8123 | Smart home hub (`ha.amer.dev`) |
| Technitium | host | 53, 5380 | DNS server (replaced Pi-hole + BIND9) |
| Whisper | bridge | 10300 | Speech-to-text (Wyoming protocol) |
| Piper | bridge | 10200 | Text-to-speech (Wyoming protocol) |
| OpenWakeWord | bridge | 10400 | Wake word detection |
| Mosquitto | bridge | 1883 | MQTT broker (Zigbee2MQTT, HA) |
| Zigbee2MQTT | bridge | 8080 | Zigbee coordinator bridge |
| Postgres 16 | bridge | 5432 | Primary database (pgvector); hosts app DBs (`agent_kb`, `todo`) |
| MongoDB | bridge | 27017 | UniFi controller database |
| Node Exporter | bridge | 9100 | Host metrics for Prometheus |

### Runners stack (`runners/compose.yaml`)

Five repo-scoped GitHub Actions runners (k3s-runners, ecdysis, llm-manager, llm-agents, photos).
ARM64 builds for multi-arch Docker images.

### Komodo stack (`komodo/compose.yaml`)

| Service | Port | Purpose |
|---------|------|---------|
| Komodo Core | 9120 | GitOps UI and API (v2.1.2) |
| Komodo Periphery | 8120 | Docker agent with `bws` CLI (custom image) |
| FerretDB | — | MongoDB-compatible database for Komodo |
| Postgres (DocumentDB) | — | Storage backend for FerretDB |

### Other (native macOS)

| Service | Port | Purpose |
|---------|------|---------|
| Ollama | 11434 | LLM inference (Metal GPU) |
| BlueBubbles | 1234 | iMessage proxy |

## Komodo GitOps

### Architecture

```
GitHub push
    │
    ▼
pubhooks.amer.dev (k3s Traefik proxy)
    │
    ├── /listener/github/sync/mac-mini-compose/sync    → ResourceSync
    ├── /listener/github/stack/<services-id>/deploy     → Services deploy
    └── /listener/github/stack/<runners-id>/deploy      → Runners deploy
    │
    ▼
Komodo Core (Mac Mini:9120)
    │
    ▼
pre_deploy: fetch secrets from BWS via bws CLI
    │
    ▼
docker compose up -d
```

### Webhooks

Three GitHub webhooks on `amerenda/mac-mini-compose`, all proxied through
`pubhooks.amer.dev` (a k3s IngressRoute that forwards `/listener/github/*` to the
Mac Mini's Komodo Core).

| Webhook | Endpoint | Purpose |
|---------|----------|---------|
| ResourceSync | `.../sync/mac-mini-compose/sync` | Update stack definitions from TOML |
| Services deploy | `.../stack/.../deploy` | Deploy services stack |
| Runners deploy | `.../stack/.../deploy` | Deploy runners stack |

All use `komodo-dean-webhook-secret` from BWS as the HMAC secret.

!!! warning "ResourceSync webhook bug"
    The ResourceSync `/sync` webhook authenticates but does not trigger execution.
    This is tracked at [moghtech/komodo#1120](https://github.com/moghtech/komodo/issues/1120).
    Stack deploy webhooks work correctly. ResourceSync falls back to 5-minute polling.

### Resource Sync files

| File | Purpose |
|------|---------|
| `resource-sync/sync.toml` | Defines the ResourceSync resource (repo, branch, resource path) |
| `resource-sync/stacks.toml` | Defines the two stacks with `pre_deploy` scripts |

Both stacks have `deploy = true` — Komodo auto-deploys after sync.

### Upgrading Komodo

1. Update `COMPOSE_KOMODO_IMAGE_TAG` in `komodo/compose.env`
2. Update the base image tag in `komodo/Dockerfile.periphery`
3. On the Mini: `cd ~/mac-mini-compose/komodo && docker compose --env-file compose.env build periphery && docker compose --env-file compose.env up -d`

The Komodo stack has `komodo.skip` labels — it does NOT auto-deploy via webhooks.

### Manually triggering a sync

If the ResourceSync shows "Pending" in the UI:

```bash
ssh mini
export PATH="$HOME/.orbstack/bin:$PATH"
ADMIN_PASS=$(cat ~/mac-mini-compose/komodo/secrets/komodo-dean-admin-password)
JWT=$(curl -sf http://localhost:9120/auth/login/LoginLocalUser \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PASS\"}" | jq -r ".data.jwt")
curl -sf http://localhost:9120/execute/RunSync \
  -H "Content-Type: application/json" \
  -H "Authorization: $JWT" \
  -d '{"sync":"mac-mini-compose"}'
```

## Secrets

BWS is the single source of truth. Three triggers refresh secrets:

| Trigger | Mechanism | When |
|---------|-----------|------|
| Boot | LaunchDaemon `inject-secrets.sh` | Every macOS boot |
| Ansible | Playbook runs `inject-secrets.sh` | On playbook run |
| Komodo deploy | `stacks.toml` `pre_deploy` | On stack deploy/sync |

See the [repo README](https://github.com/amerenda/mac-mini-compose) for secret locations and rotation procedures.

## Setup

```bash
ansible-playbook -i inventory/inventory.ini playbooks/infrastructure/setup-macmini.yml \
  --extra-vars "bws_access_token=<YOUR_BWS_TOKEN>"
```

### Manual steps after playbook

- **Tailscale**: `ssh mini && tailscale up --accept-routes --ssh`
- **Auto-login**: System Settings > Users & Groups > Automatic Login
- **BlueBubbles**: GUI setup (Full Disk Access, SIP disable, sign in)

## Known Issues

### OrbStack host networking after reboot

`network_mode: host` doesn't bridge containers to LAN after reboot. A LaunchAgent
workaround tests connectivity and restarts OrbStack if needed.

### OrbStack VirtFS directory cache

New directories from `git pull` inside containers don't propagate via VirtFS.
A LaunchAgent runs `scripts/sync-stacks.sh` every 60 seconds on the host, doing
`git fetch && reset --hard` and restarting Periphery if the directory structure changed.
