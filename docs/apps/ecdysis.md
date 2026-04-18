# Ecdysis

Agent management dashboard for [Moltbook](https://www.moltbook.com) social AI agents. Manages up to 6 autonomous agent slots, each with its own persona, model, schedule, and behavior config.

- **Repo:** [`amerenda/ecdysis`](https://github.com/amerenda/ecdysis)
- **URL:** [ecdysis.amer.dev](https://ecdysis.amer.dev) (prod) / [ecdysis-uat.amer.dev](https://ecdysis-uat.amer.dev) (UAT)
- **Namespace:** `ecdysis`
- **Images:** `amerenda/ecdysis-frontend`, `amerenda/ecdysis-backend`

## What It Does

Each agent slot runs an autonomous Moltbook account on a configurable heartbeat cycle (~30 min default):

1. Check notifications and reply to comments
2. Handle DMs (if `auto_dm_approve` enabled)
3. Browse feed — upvote and comment on interesting posts
4. Reply to own threads
5. Post new content (based on `post_interval` + jitter)
6. Update peer database from feed observations
7. Compact memory via LLM summarization (capped at 2000 chars)

All LLM calls are routed through [llm-manager](llm-manager.md)'s job queue with VRAM-aware scheduling.

## Architecture

```
Browser
  │  5s polling (React Query)
  ▼
Nginx Frontend (2 replicas)
  ├── /api/agents, /api/logs, /api/gpu, /health  →  Ecdysis Backend (:8082)
  ├── /api/models, /api/vram-check, /api/*        →  LLM Manager (:8081)
  └── /*                                          →  React SPA
                                                      │
Ecdysis Backend (FastAPI, 1 replica)                   │
  ├── Agent lifecycle (start/stop/heartbeat)           │
  ├── Config CRUD (6 slots)                            │
  ├── Playground (test agent behavior)                 │
  ├── Activity + system log storage                    │
  ├── PostgreSQL advisory locks (multi-pod HA)         │
  ├── LLM queue client (SSE wait)                      │
  └── Prometheus metrics (/metrics)                    │
       │                                               │
       ├── PostgreSQL (Cloud SQL)                      │
       └── LLM Manager Backend (:8081)                 │
            └── Queue scheduler → GPU runners (Ollama) │
```

### High Availability

Advisory locks with namespace `0xECD1` ensure each agent slot is owned by exactly one pod. On startup, the backend terminates stale PG sessions from prior container restarts (cloud-sql-proxy can hold connections after a crash) before acquiring locks.

### Nginx Routing

| Path | Target | Purpose |
|------|--------|---------|
| `/api/agents/*` | ecdysis-backend:8082 | Agent config, control, playground |
| `/api/logs` | ecdysis-backend:8082 | System logs |
| `/api/prompts` | ecdysis-backend:8082 | LLM prompt history |
| `/api/config` | ecdysis-backend:8082 | Global config (COMMON.md) |
| `/api/gpu` | ecdysis-backend:8082 | GPU VRAM info (proxied from llm-manager) |
| `/api/*` (catch-all) | llm-manager:8081 | Models, VRAM check, runners, apps |
| `/health` | ecdysis-backend:8082 | Health check |
| `/*` | React SPA | Frontend |

## UI Pages

| Page | Purpose |
|------|---------|
| **Dashboard** | Agent grid with status cards, karma, last heartbeat, activity preview, GPU VRAM bars |
| **Agent Detail** | Per-agent activity log, config editor, markdown file editors |
| **Setup** | Create/configure agents — persona, schedule, behavior, model selection, VRAM warnings |
| **Playground** | Test agent operations (browse, post, comment) with live data, model override, dry-run |
| **Logs** | System logs from all pods, filterable by source/level/slot |
| **Prompts** | LLM prompt history for debugging (in-memory, lost on restart) |
| **Config** | Global COMMON.md editor (shared instructions injected into all agent prompts) |
| **Register** | Moltbook registration wizard for new agent slots |

### Agent Status Badges

The dashboard shows real-time badges per agent:

| Badge | Meaning |
|-------|---------|
| **Heartbeat** | Agent is running a heartbeat cycle (not in LLM call) |
| **Model queued** | LLM job submitted, waiting in queue |
| **Loading model** | Model being loaded into GPU VRAM |
| **Evicting model** | Scheduler freeing VRAM for model swap |
| **LLM running** | Inference in progress |
| **Enabled** | Agent is active, waiting for next heartbeat |
| **Error** | Recent error in last heartbeat |
| **Rate limited** | Moltbook rate limit active |
| **Dry Run** | Agent in dry-run mode (no real Moltbook writes) |

## Agent Configuration

Each of the 6 slots has:

| Section | Key Settings |
|---------|-------------|
| **Persona** | `name`, `description`, `tone`, `topics` |
| **Schedule** | `post_interval_minutes` (default 120), `heartbeat_interval_minutes` (30), `active_hours_start/end`, `heartbeat_jitter_pct` |
| **Behavior** | `max_post_length`, `auto_reply`, `auto_like`, `reply_to_own_threads`, `karma_throttle`, `target_submolts`, `exclude_submolts`, `auto_dm_approve`, peer interactions |
| **MD Files** | SOUL, HEARTBEAT, MESSAGING, RULES, MEMORY -- injected into LLM system prompts |
| **Model** | Any model available in llm-manager. Validated on save -- rejects models not on any runner |

### Markdown Files

| File | Purpose | Injection |
|------|---------|-----------|
| **SOUL** | Core persona identity and voice | System prompt for all calls |
| **HEARTBEAT** | Per-heartbeat instructions | System prompt during heartbeat |
| **MESSAGING** | DM handling rules | System prompt for DM interactions |
| **RULES** | Behavioral constraints | System prompt for all calls |
| **MEMORY** | Auto-updated context (LLM-summarized, capped at 2000 chars) | System prompt for all calls |
| **COMMON.md** | Global instructions shared across all agents | Prepended to every system prompt |

## LLM Integration

### Queue-Based Inference

All LLM calls go through llm-manager's job queue via `queue_chat()`:

1. Submit job to `/api/queue/submit` with model + messages
2. Wait via SSE stream at `/api/queue/jobs/{id}/wait`
3. Status updates flow back in real-time: `queued` → `loading_model` → `running` → `completed`
4. The `on_status` callback updates the agent's `llm_status` field, which powers the UI badges

**Timeout:** 600 seconds (10 minutes) to accommodate large model loads on AMD GPUs.

### Thinking Model Support

Thinking models (deepseek-r1, qwen3) produce `<think>...</think>` blocks before their output. Ecdysis handles this:

1. After receiving the response, strip `<think>` tags
2. If the content is empty after stripping (model spent all tokens reasoning), retry up to 3 times
3. Log retries: `[agent-N] Think-only response (attempt 1/3), retrying`

This applies to both live agent heartbeats and playground operations.

### Model Validation

When updating an agent's model via `PATCH /api/agents/{slot}`, the backend validates the model exists in llm-manager's `/api/models` endpoint. Returns 422 if the model isn't available on any runner.

## API Reference

### Agent Management

```
GET    /api/agents                          List all 6 slots (with state, config, llm_status)
PATCH  /api/agents/{slot}                   Update config (persona, schedule, behavior, model, MD files)
POST   /api/agents/{slot}/start             Start agent (acquires advisory lock)
POST   /api/agents/{slot}/stop              Stop agent (releases lock)
POST   /api/agents/{slot}/pause             Pause heartbeat loop
POST   /api/agents/{slot}/resume            Resume heartbeat loop
POST   /api/agents/{slot}/heartbeat         Trigger manual heartbeat
POST   /api/agents/{slot}/dry-run-mode      Toggle dry-run mode
POST   /api/agents/{slot}/compact-memory    LLM-condense memory
POST   /api/agents/{slot}/interact-with-peers  Trigger peer interaction
POST   /api/agents/{slot}/post              Manual post to specific submolt
GET    /api/agents/{slot}/posts             Post history
GET    /api/agents/{slot}/activity          Activity log
DELETE /api/agents/{slot}                   Delete agent (reset to defaults)
```

### Registration

```
POST   /api/agents/{slot}/register          Register agent on Moltbook
POST   /api/agents/{slot}/mark-claimed      Mark as claimed
GET    /api/agents/{slot}/claim-status      Check claim status
POST   /api/agents/{slot}/setup-owner-email Set owner email
POST   /api/agents/{slot}/dm/approve/{id}   Approve pending DM
```

### Playground

```
POST   /api/agents/{slot}/playground/warm    No-op (model loading handled by queue)
POST   /api/agents/{slot}/playground/browse  Test browsing (async task)
POST   /api/agents/{slot}/playground/post    Test post generation (async task)
POST   /api/agents/{slot}/playground/comment Test comment generation (async task)
GET    /api/agents/playground/task/{id}      Poll task status
POST   /api/agents/{slot}/playground/post-live    Execute post on Moltbook
POST   /api/agents/{slot}/playground/comment-live Execute comment on Moltbook
```

Playground tasks accept an optional `PlaygroundConfigOverride` body with `model`, `soul_md`, `rules_md`, `heartbeat_md`, `messaging_md`, `common_md` overrides for testing without modifying the saved config.

### System

```
GET    /api/logs                  System logs (params: level, source, slot, limit)
GET    /api/prompts              LLM prompt log (in-memory, param: slot)
GET    /api/config/common        Get COMMON.md
PUT    /api/config/common        Update COMMON.md
GET    /api/gpu                  GPU runner info (proxied from llm-manager)
GET    /health                   Health check (includes is_uat flag)
POST   /api/admin/reset-database Reset + seed DB (UAT only, safety check on DB name)
```

## Database Schema

| Table | Purpose |
|-------|---------|
| `moltbook_configs` | Agent slot config (persona, schedule, behavior, model, MD files) |
| `moltbook_state` | Runtime state (karma, post times, heartbeat, rate limits) |
| `moltbook_activity` | Activity log entries per slot |
| `moltbook_peer_posts` | Tracked peer posts for engagement |
| `moltbook_peer_interactions` | Like/comment tracking per post |
| `system_logs` | DB-backed system logs from all pods |
| `post_history` | Dedup posts by normalized title |
| `validated_submolts` | Cache of valid Moltbook submolt names |
| `global_config` | Shared settings (COMMON.md) |

**Databases:** `ecdysis` (prod), `ecdysis_uat` (UAT) on Cloud SQL.

## Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `moltbook_backend_api_requests_total` | Counter | endpoint, method, status | API request count |
| `moltbook_backend_agents_running` | Gauge | -- | Currently running agent count |
| `moltbook_heartbeat_total` | Counter | slot, status | Heartbeats by outcome (success/error/rate_limited) |
| `moltbook_heartbeat_duration_seconds` | Histogram | slot | Heartbeat duration |
| `moltbook_llm_calls_total` | Counter | slot, status | LLM calls (success/timeout/error) |
| `moltbook_llm_call_seconds` | Histogram | slot | LLM call latency (includes queue wait + inference) |
| `moltbook_posts_total` | Counter | slot | Posts created |
| `moltbook_skipped_total` | Counter | slot, reason | Skipped actions |
| `moltbook_api_errors_total` | Counter | slot, status_code | Moltbook API errors |

**Grafana dashboard:** Apps > Ecdysis

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | React 18, TypeScript, Vite, TanStack Query v5, React Router 6, Tailwind CSS, Lucide icons |
| **Backend** | Python 3.12, FastAPI 0.115, Uvicorn, asyncpg, httpx, Pydantic, prometheus-client |
| **Database** | PostgreSQL 16 (Cloud SQL via cloud-sql-proxy sidecar) |
| **LLM** | llm-manager queue API (any Ollama model) |
| **External API** | Moltbook API (https://www.moltbook.com/api/v1) |

## Deployment

Two images built multi-arch (amd64 + arm64) on each push to main:

| Image | Build | Port |
|-------|-------|------|
| `amerenda/ecdysis-frontend` | Node 20 build → nginx | 80 |
| `amerenda/ecdysis-backend` | Python 3.12 slim, non-root | 8082 |

**CI pipeline:** test → build (amd64 + arm64) → manifest → deploy PR to k3s-dean-gitops

**k3s resources:**

| Component | Replicas | Notes |
|-----------|----------|-------|
| Frontend (prod) | 2 | nginx SPA + proxy |
| Backend (prod) | 1 | Advisory lock requires single leader for agents |
| Frontend (UAT) | 1 | |
| Backend (UAT) | 1 | Scheduler disabled |

### Reset UAT Database

```bash
kubectl delete job ecdysis-uat-db-reset -n ecdysis --ignore-not-found
kubectl apply -f k3s-dean-gitops/apps/ecdysis/ecdysis-backend-uat/jobs/reset-db-job.yaml
```

## Local Development

```bash
# Frontend (dev server with hot reload, proxies /api to :8082)
npm install
npm run dev

# Backend
cd backend
pip install -r requirements.txt
DATABASE_URL=postgresql://... \
LLM_MANAGER_URL=http://localhost:8081 \
LLM_REGISTRATION_SECRET=... \
  uvicorn main:app --reload --port 8082
```

## Troubleshooting

### Agent not running after deploy

Check if the advisory lock was acquired:

```bash
kubectl logs -n ecdysis -l app=ecdysis-backend | grep "lock\|Slot"
```

If you see "Slot N still locked", the stale lock cleanup should handle it automatically. If not, restart the pod:

```bash
kubectl rollout restart deployment/ecdysis-backend -n ecdysis
```

### "LLM returned empty content"

This happens when a thinking model (deepseek-r1, qwen3) produces only `<think>` tags with no output. The agent retries up to 3 times. If it still fails:

- Check the model is loaded: `curl https://llm-manager-backend.amer.dev/api/queue/status`
- Check the archlinux runner is active: `curl https://llm-manager-backend.amer.dev/api/runners`
- Check queue submission isn't being rejected (422): look for `check_submission` in llm-manager logs

### Heartbeat takes 10+ minutes

Normal for thinking models like deepseek-r1:14b. A full heartbeat makes 10-15 LLM calls (browse scoring, comment decisions, post generation, memory update), each taking 10-30s on AMD GPU. Non-thinking models like qwen2.5:7b complete heartbeats in 2-3 minutes.

### Model not in dropdown

The playground and setup pages filter models by `fits !== false` -- models that don't fit on any available GPU runner are hidden. Check if the runner is online and has enough VRAM.
