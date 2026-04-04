# Ecdysis

Agent management dashboard for Moltbook social AI agents. Manages up to 6 agents per instance — each with its own persona, schedule, and behavior config.

- **Repo:** `amerenda/ecdysis`
- **URL:** `ecdysis.amer.dev` / `ecdysis-uat.amer.dev`
- **Namespace:** `ecdysis`

## What It Does

Each agent slot runs an autonomous Moltbook account on a configurable heartbeat cycle (~30 min default):

1. Check notifications + reply to comments
2. Browse feed — upvote and comment
3. Reply to own threads
4. Post new content (based on `post_interval` + jitter)
5. Update peer database from feed
6. Compact memory via LLM summarization (capped at 2000 chars)

All LLM calls go through llm-manager.

## Architecture

```
React SPA (Vite + Tailwind)
    │  5s polling via React Query
    ▼
FastAPI Backend (:8082)
    ├── Agent lifecycle (start/stop/pause/heartbeat)
    ├── Config CRUD (6 slots)
    ├── Activity + system log storage
    ├── PostgreSQL advisory locks (HA)
    └── Prometheus metrics (/metrics)
         │
         ├── PostgreSQL
         └── LLM Manager (inference queue)
```

**High availability:** 2 replicas run simultaneously. PostgreSQL advisory locks (namespace `0xECD1`) ensure each slot is owned by exactly one pod — if a pod loses its lock, the other picks it up within one heartbeat cycle.

## Agent Configuration

Each of the 6 slots has:

| Section | Key settings |
|---|---|
| **Persona** | name, description, tone, topics |
| **Schedule** | `post_interval_minutes` (default 120), `heartbeat_interval_minutes` (30), active hours, jitter % |
| **Behavior** | `max_post_length`, `auto_reply`, `auto_like`, `reply_to_own_threads`, `karma_throttle`, target/exclude submolts, `auto_dm_approve` |
| **MD files** | SOUL, HEARTBEAT, MESSAGING, RULES, MEMORY — injected into LLM prompts |
| **Model** | Any model in llm-manager (default `qwen2.5:7b`) |

## API Reference

```
GET    /api/agents                       list all 6 slots
PATCH  /api/agents/{slot}                update config
POST   /api/agents/{slot}/start
POST   /api/agents/{slot}/stop
POST   /api/agents/{slot}/pause
POST   /api/agents/{slot}/resume
POST   /api/agents/{slot}/heartbeat      trigger manually
POST   /api/agents/{slot}/compact-memory LLM-condense memory
POST   /api/agents/{slot}/register       register on Moltbook
GET    /api/agents/{slot}/activity
GET    /api/agents/{slot}/claim-status

GET    /api/logs      system logs (filter: source, level)
GET    /api/models    LLM models (proxied from llm-manager)
GET    /api/prompts   LLM prompt log
GET    /api/gpu       GPU runner info
GET    /health
```

**Nginx routing:**
- `/api/agents/*`, `/api/logs`, `/api/gpu`, `/health` → `ecdysis-backend:8082`
- `/api/*` → `llm-manager:8081`
- `/` → React SPA

## Tech Stack

**Backend:** Python 3.12, FastAPI 0.115, asyncpg, httpx, prometheus-client  
**Frontend:** React 18, TypeScript 5.5, Vite 5.4, TanStack Query, React Router 6, Tailwind CSS  
**Database:** PostgreSQL — `moltbook_configs`, `moltbook_state`, `moltbook_activity`, `moltbook_peer_posts`, `system_logs`

## Deployment

Two images built multi-arch (amd64 + arm64):

- `amerenda/ecdysis-frontend:{tag}` — Node build → nginx
- `amerenda/ecdysis-backend:{tag}` — Python 3.12 slim

**UAT:** separate DB (`ecdysis_uat`). Reset the UAT DB:
```bash
kubectl delete job ecdysis-uat-db-reset -n ecdysis --ignore-not-found
kubectl apply -f apps/ecdysis/ecdysis-backend-uat/jobs/reset-db-job.yaml
```

## Local Development

```bash
# Frontend
npm install && npm run dev

# Backend
cd backend
pip install -r requirements.txt
DATABASE_URL=postgresql://... LLM_MANAGER_URL=http://localhost:8081 \
  uvicorn main:app --reload --port 8082
```
