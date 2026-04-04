# LLM Manager

Centralized GPU resource manager and job queue scheduler. Routes all AI inference workloads (Ollama text models, ComfyUI image generation) through a VRAM-aware async queue.

- **Repo:** `amerenda/llm-manager`
- **UI:** `llm-manager.amer.dev` (Tailscale-only)
- **API:** `llm-manager-backend.amer.dev` (externally reachable — agents + apps)
- **Namespace:** `llm-manager`

## Architecture

```
GPU Host (bare metal)              k3s Cluster
┌─────────────────────┐            ┌──────────────────────────────┐
│ Agent (Docker)      │            │ Backend (FastAPI, 2 replicas) │
│  - Ollama :11434    │──HTTPS──▶  │  - VRAM-aware scheduler       │
│  - ComfyUI :8188    │◀──HTTP──   │  - Job queue (PostgreSQL)     │
│  - Heartbeat 30s    │  (LAN)     │  - App registry               │
│  - PSK auth         │            │  - OpenAI-compatible API       │
└─────────────────────┘            │  - GitHub OAuth admin         │
                                   └──────────────┬───────────────┘
                                                  │
                                          PostgreSQL (Longhorn, 10Gi)
                                          React Dashboard (nginx)
```

Multiple GPU hosts can register. The scheduler picks the runner with available VRAM.

## Components

### Agent (runs on GPU hosts)

Docker Compose service on bare-metal machines (murderbot, archlinux):

- Wraps Ollama (text) and ComfyUI (image generation)
- Self-registers with backend on startup, sends heartbeat every 30s
- PSK-authenticated (all endpoints except `/health` and `/metrics`)
- Exposes HTTPS on port 8090 (self-signed cert)

### Backend (k3s)

Stateless FastAPI service — 2 replicas, single active scheduler via PostgreSQL advisory lock:

- **Job queue** — VRAM-aware scheduling with model eviction
- **App registry** — API key issuance and management
- **Profiles** — Named model/checkpoint sets, activate with one call
- **OpenAI-compatible API** — Drop-in for apps using `/v1/chat/completions`
- **Anthropic cloud integration** — Encrypted API key storage, cloud model routing
- **GitHub OAuth** — Admin dashboard authentication

### Frontend (k3s)

React SPA (2 replicas) — model management, queue monitoring, profile editor, app registry.

## Job Queue & VRAM Management

**Job lifecycle:** `queued` → `waiting_for_eviction` → `running` → `completed|failed|cancelled`

**Scheduler logic:**
1. Batch jobs by model — already-loaded models run first
2. Auto-load missing models via Ollama
3. **Eviction** when VRAM is full:
   - `do_not_evict=true` models are never touched
   - Idle models evicted before busy ones; oldest-loaded first
   - Default: wait up to 5 min for active jobs to finish before evicting
4. Pre-validates model VRAM estimate before accepting submissions

Scheduler runs as a single async worker — one of the two backend pods holds the PostgreSQL advisory lock (ID: 900001).

## API Reference

**OpenAI-compatible (Bearer token):**
```
POST /v1/chat/completions      chat inference (streaming supported)
POST /v1/images/generations    image generation via ComfyUI
```

**Queue (Bearer token):**
```
POST   /api/queue/submit                  submit job
POST   /api/queue/submit-batch            submit batch
GET    /api/queue/jobs/{job_id}           poll status
GET    /api/queue/jobs/{job_id}/wait      SSE stream — blocks until done
DELETE /api/queue/jobs/{job_id}           cancel
GET    /api/queue/status                  queue overview
GET/PATCH /api/models/{model}/settings   eviction settings
```

**Runner management (PSK auth):**
```
POST /api/runners/register     agent self-registration
POST /api/runners/heartbeat    keepalive
GET  /api/runners              list active runners (last 90s)
```

**App registry:**
```
POST /api/apps/discover        auto-register with registration secret → returns API key
POST /api/apps/register        manual registration
GET  /api/apps                 list apps (admin)
POST /api/apps/{id}/approve    approve pending app (admin)
```

**LLM control (PSK or Bearer):**
```
GET  /api/llm/models           list all models
POST /api/llm/models/pull      pull Ollama model
POST /api/llm/models/load      load into VRAM
POST /api/llm/models/unload    unload from VRAM
```

**Profiles:**
```
GET/POST        /api/profiles
GET/PATCH       /api/profiles/{id}
POST            /api/profiles/{id}/activate
POST            /api/profiles/{id}/models
```

## Connecting an App

Apps authenticate with a Bearer token obtained via auto-discovery:

```python
# Register once — returns API key
response = httpx.post(
    "https://llm-manager-backend.amer.dev/api/apps/discover",
    json={"name": "my-app", "secret": LLM_REGISTRATION_SECRET}
)
api_key = response.json()["api_key"]

# Submit a job
httpx.post("/api/queue/submit", json={
    "model": "qwen2.5:7b",
    "messages": [{"role": "user", "content": "Hello"}]
}, headers={"Authorization": f"Bearer {api_key}"})
```

## Deployment

**Images** (multi-arch, amd64 + arm64):
- `amerenda/llm-manager-backend:{tag}`
- `amerenda/llm-manager-frontend:{tag}`

**Secrets** (BWS via ExternalSecret):

| BWS key | Purpose |
|---|---|
| `llm-manager-agent-psk` | Backend ↔ agent auth |
| `llm-manager-registration-secret` | App auto-discovery |
| `llm-manager-postgres-url` | PostgreSQL DSN |
| `llm-manager-postgres-password` | Postgres pod |
| `github-oauth` | Admin dashboard (client-id + client-secret) |
| `session-secret` | JWT signing |
| `api-key-encryption-key` | Fernet key for stored cloud API keys |

**UAT:** separate namespace with `DISABLE_SCHEDULER=true` and `DISABLE_AUTH=true`.

## Adding a GPU Runner

1. Set up Docker Compose on the GPU host using `agent/docker-compose.yml`
2. Configure `agent/.env`:
   ```
   LLM_MANAGER_AGENT_PSK=<psk from BWS>
   BACKEND_URL=https://llm-manager-backend.amer.dev
   AGENT_ADDRESS=http://<host-lan-ip>:8090
   ```
3. Start: `docker compose up -d`
4. Agent self-registers; appears in dashboard within 90 seconds

AMD GPU hosts use `docker-compose.amd.yml` and may need `HSA_OVERRIDE_GFX_VERSION`.
