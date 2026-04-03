# Mac Mini M4

Core services host. Managed via `amerenda/mac-mini-compose` (Docker Compose) + Komodo.

## Services

| Service | Description |
|---------|-------------|
| Postgres 16 | General-purpose DB with pgvector; hosts all app databases |
| Home Assistant | Home automation, exposed at `ha.amer.dev` |
| Ollama | Local LLM inference (Metal GPU) |
| Mycroft agent | AI agent framework (Argo Workflows + pgvector KB) |
| Voice pipeline | Whisper STT, Piper TTS, OpenWakeWord |
| Komodo | Docker Compose orchestrator with GitHub webhook |
| Traefik | Reverse proxy for Mac Mini services |

## Access

- Komodo UI: internal only
- Services exposed via Traefik at `*.amer.dev`

## Deployment

- `mac-mini-compose` repo tagged `stable` for production
- Komodo polls GitHub every 5 minutes; webhook fires on push (LAN)
- Ansible playbook (`mac-mini.yml`) manages system-level config and Ollama install
