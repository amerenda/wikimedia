# Mycroft

AI agent platform for engineering and research tasks. Agents run as ephemeral Argo Workflow pods on k3s, orchestrated by a coordinator service.

- **Repo:** `amerenda/mycroft`
- **Agent Studio:** `mycroft.amer.dev`
- **Namespace:** `mycroft`

## Architecture

```
Telegram / API / Agent Studio UI
    │
    ▼
Coordinator (FastAPI :8080)
    ├── Intent classification (qwen2.5:7b)
    ├── Task CRUD (PostgreSQL)
    ├── Research pipeline orchestration
    ├── Argo Workflow submission (k8s API)
    ├── Sazed report posting (when configured)
    └── Telegram notifications (success only)
            │
            ▼
    Argo Workflow Pod (ephemeral, per task)
    ┌─────────────────────────────┐
    │ Agent Runtime               │
    │  1. Load manifest + tools   │
    │  2. Recall KB context       │
    │  3. LLM chat loop           │
    │  4. Execute tools           │
    │  5. Persist conversation    │
    └─────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
   LLM Manager     Knowledge Base    SearXNG
   (job queue)    (pgvector)        (web search)
```

## Components

### Coordinator

FastAPI service managing the full task lifecycle:

- **Telegram polling** — receives messages, classifies intent, routes to agent type
- **Task management** — CRUD with concurrency limits per agent type
- **Research pipeline** — two-phase gather→write for regular/deep research
- **Argo submission** — creates `WorkflowTemplate` refs via k8s API, monitors completion
- **Agent Studio UI** — `mycroft.amer.dev` — task runner, reports, model selection, advanced options
- **Prometheus metrics** — `/metrics` endpoint, scraped by Prometheus

### Agent Runtime

Thin loop (~250 lines) running inside each ephemeral workflow pod:

1. Read task instruction + config from KB
2. Vector-search KB for relevant context (top 5 results)
3. Build system prompt from agent manifest + effort-specific supplement
4. Iterate: LLM → tool calls → results → persist conversation → repeat
5. Write result to `/agents/{type}/results/{task_id}`

**Iteration limits:** per-task configurable from UI/API, capped globally at 30.
**Resume safety:** conversation persisted to KB after each tool-call round.
**Tools override:** pipeline phases can restrict tool sets (e.g., gatherer has no write_file).

### Knowledge Base (KB)

PostgreSQL + pgvector on Mac Mini. All agent I/O goes through scoped paths:

| Path pattern | Purpose |
|---|---|
| `/agents/{type}/inbox/{task_id}` | Task instructions |
| `/tasks/{task_id}/conversation` | Conversation history (JSON) |
| `/agents/{type}/results/{task_id}` | Final output |
| `/notifications/alex/{task_id}` | Errors / alerts (logged, not sent to Telegram) |
| `/research`, `/wiki` | Shared read-only context |

Vector search: `all-MiniLM-L6-v2` (384-dim).

### SearXNG

Self-hosted meta search engine in the `mycroft` namespace. Aggregates from Google, Bing, DuckDuckGo, Wikipedia, GitHub. No API keys, no CAPTCHAs, no rate limits.

- **Service:** `mycroft-search:8080`
- **API:** `http://mycroft-search.mycroft.svc:8080/search?q=...&format=json`

### LLM Manager Integration

All inference goes through llm-manager's job queue:

1. Submit job to `/api/queue/submit`
2. Poll `/api/queue/jobs/{job_id}` until terminal state (10-min timeout)
3. Parse OpenAI-compatible response (content + tool_calls)
4. `max_tokens=4096` default (thinking models need headroom)

## Agents

### Coder

| Property | Value |
|---|---|
| Default model | `qwen3:14b` |
| Max iterations | 30 (global cap) |
| Tools | files, git, github, shell |
| Triggers | Telegram (`intent: engineering`), API, Agent Studio |

Phase-based protocol: Understand (clone, read) → Implement (patch, write) → Ship (commit, push, PR).

### Researcher

| Property | Value |
|---|---|
| Research model | `qwen3.5:9b` (gatherer) |
| Writer model | `llama3.1:8b` (report writer) |
| Summarization model | `qwen2.5:7b` (web_read secondary LLM) |
| Tools | web_search, web_read, wiki_read, run_command (gather) / write_file, read_file (write) |
| Triggers | Telegram (`intent: research`), API, Agent Studio |

#### Research Pipeline (regular/deep tiers)

Two-phase Argo DAG — each phase is a separate task:

```
Phase 1: GATHERER (qwen3.5:9b)
  ├── web_search via SearXNG (real results, no CAPTCHAs)
  ├── web_read (crawl4ai → trafilatura → markdownify → basic)
  │   └── Large pages summarized by qwen2.5:7b (OpenClaude pattern)
  ├── wiki_read (Wikipedia REST API, clean JSON)
  └── Exits naturally when model responds with text
  
Coordinator captures findings, launches Phase 2

Phase 2: WRITER (llama3.1:8b)
  ├── Receives all gatherer findings as input
  ├── write_file → /workspace/report.md
  └── Cannot search — only writes
```

#### Effort Tiers

| Tier | Gather iterations | Writer iterations | Behavior |
|---|---|---|---|
| **Light** | 2 (single task) | 0 | Quick search, respond directly to Telegram. No report. |
| **Regular** | 5 | 3 | Multi-source research → structured report |
| **Deep** | 8 | 5 | Comprehensive research → adversarial review → report |

#### Web Content Extraction

Four-tier fallback for `web_read`:

1. **crawl4ai** — headless browser + markdown (researcher image only)
2. **trafilatura** — content extraction from raw HTML (no browser)
3. **markdownify** — HTML → markdown conversion
4. **basic regex** — strip scripts/styles/nav, then all tags

Pages >5000 chars are automatically summarized by `qwen2.5:7b` before being returned to the research model. This prevents context pollution from raw HTML.

#### Knowledge Cutoff Awareness

The researcher prompt explicitly addresses training data staleness:

> "Your job is to discover the present, not recall the past. If you think something doesn't exist yet — search for it. You're probably wrong."

### Planned Agents

| Agent | Purpose | Status |
|---|---|---|
| Planner | Interactive planning with human input | Designed |
| Reviewer | Adversarial code review, PR testing | Designed |
| Documenter | Auto-update READMEs and docs | Designed |
| QA | End-to-end testing in UAT | Designed |

## Tools

| Group | Tools | Used by |
|---|---|---|
| `files` | read_file, write_file, patch_file, search_files, list_files | Coder, Writer |
| `web` | web_search (SearXNG), web_read (crawl4ai/trafilatura), wiki_read (Wikipedia API) | Researcher |
| `git` | clone, checkout-branch, add, commit, push, diff | Coder |
| `github` | create-pr, comment | Coder |
| `shell` | run_command (bash, 120s timeout) | Coder, Researcher |

Tool schemas are versioned in agent-kb (`tool_schemas` table) with CRUD API at `/api/tools/schemas`.

## Agent Studio UI

Web interface at `mycroft.amer.dev`:

- **Test Runner** — select agent type (coder/researcher), model, effort level, advanced options (max_tokens, temperature, max_iterations)
- **Reports** — browse research reports with markdown rendering
- **Tasks** — list, view conversations, delete

Runner dropdown: Mycroft (default) or Forge (legacy, for comparison).

## Images

Built multi-arch (amd64 + arm64) on every push to `main`:

| Image | Purpose | Size |
|---|---|---|
| `amerenda/mycroft:agent-base-{tag}` | Shared base — Python deps, tools, runtime | ~300MB |
| `amerenda/mycroft:agent-coder-{tag}` | Extends base — Node.js, gh CLI, pytest | ~400MB |
| `amerenda/mycroft:agent-researcher-{tag}` | Extends base — crawl4ai, Playwright, trafilatura | ~1GB |
| `amerenda/mycroft:coordinator-{tag}` | Coordinator service + Forge binary | ~500MB |
| `amerenda/mycroft:frontend-{tag}` | Agent Studio nginx SPA | ~30MB |

## Prometheus Metrics

Scraped at `/metrics` via ServiceMonitor.

| Metric | Type | Labels |
|---|---|---|
| `mycroft_tasks_created_total` | Counter | agent_type, trigger |
| `mycroft_tasks_completed_total` | Counter | agent_type, status |
| `mycroft_tasks_active` | Gauge | agent_type |
| `mycroft_llm_calls_total` | Counter | model |
| `mycroft_llm_queue_wait_seconds` | Histogram | model |
| `mycroft_agent_tool_calls_total` | Counter | agent_type, tool |

## Deployment

GitOps via ArgoCD:

| App | Path | Purpose |
|---|---|---|
| `app-mycroft-backend` | `apps/mycroft/backend/` | Coordinator |
| `app-mycroft-frontend` | `apps/mycroft/frontend/` | Agent Studio UI |
| `app-mycroft-workflows` | `apps/mycroft/workflows/` | Argo WorkflowTemplates |
| `app-searxng` | `apps/searxng/` | SearXNG search engine |

**Secrets** (`mycroft-credentials` ExternalSecret from BWS):

| Key | Purpose |
|---|---|
| `kb-dsn` | PostgreSQL connection |
| `llm-registration-secret` | llm-manager auto-discovery |
| `github-app-id/installation-id/private-key` | GitHub App auth for clone/push/PR |
| `telegram-bot-token` / `telegram-chat-id` | Telegram bot |
| `vikunja-token` | Todo integration |

## Model Selection Results

Tested April 2026 across multiple tasks:

| Model | Tool calling | Report writing | Research depth | Best for |
|---|---|---|---|---|
| **qwen3.5:9b** | Good | Poor (won't stop) | Excellent (8+ reads) | Gatherer |
| **llama3.1:8b** | Good | Excellent | Medium | Writer, light research |
| **qwen3:14b** | Good (thinking model) | Poor (empty templates) | Medium | Coder |
| qwen2.5:7b | Good | Noisy (git loops) | Low | Summarization secondary |
| qwen3.6:35b-a3b | Excellent | Excellent | Excellent | Too large for 17GB VRAM (needs q4_0 KV cache) |
