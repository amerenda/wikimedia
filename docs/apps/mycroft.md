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
    ├── Dynamic pipeline orchestration (custom workflows)
    ├── Argo Workflow submission (k8s API)
    ├── Report storage (local agent-kb)
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
- **Dynamic pipeline** — multi-step pipelines defined in the Workflows editor
- **Argo submission** — creates inline workflow specs via k8s API, monitors completion
- **Report store** — saves agent reports to local agent-kb (`reports` table)
- **Agent Studio UI** — `mycroft.amer.dev` — full platform control
- **In-memory log buffer** — 2000-record ring buffer exposed at `/api/logs`
- **Prometheus metrics** — `/metrics` endpoint, scraped by Prometheus
- **KB cleanup** — hourly background task deletes expired short-term records

### Agent Runtime

Thin loop (~250 lines) running inside each ephemeral workflow pod:

1. Read task instruction + config from KB inbox
2. Vector-search KB for relevant context (top 5 results)
3. Build system prompt from agent manifest + effort-specific supplement
4. Optionally append `system_suffix` from pipeline step config
5. Inject pipeline framing + context (original brief, prior step output) into first user message
6. Iterate: LLM → tool calls → results → persist conversation → repeat
7. Write result to `/agents/{type}/results/{task_id}`

**Iteration limits:** per-task configurable from UI/API, capped globally at 30.
**Resume safety:** conversation persisted to KB after each tool-call round.
**Tools override:** pipeline phases can restrict tool sets per step.

### Knowledge Base (KB)

PostgreSQL + pgvector on Mac Mini (`agent-kb` database). All agent I/O uses scoped path strings. The KB client enforces per-agent read/write permission lists based on path prefixes.

#### Memory Tiers

| Tier | TTL | Where | Purpose |
|---|---|---|---|
| **Short-term** | 7 days | `/runs/{run_id}/` | Pipeline run data — original brief, step outputs, scratch |
| **Long-term** | Permanent | `/agents/*/results/`, `/tasks/`, `/research/`, `/wiki/` | Task results, conversation history, shared knowledge |

Short-term records carry an `expires_at` timestamp. The coordinator runs hourly cleanup (`DELETE WHERE expires_at < NOW()`). The `ensure_schema()` call at startup idempotently adds the `expires_at TIMESTAMPTZ` column if it doesn't exist.

#### Path Reference

| Path pattern | TTL | Purpose |
|---|---|---|
| `/agents/{type}/inbox/{task_id}` | Long | Task instructions written by coordinator |
| `/tasks/{task_id}/conversation` | Long | Full conversation history (JSON, persisted each iteration) |
| `/agents/{type}/results/{task_id}` | Long | Final agent output |
| `/notifications/alex/{task_id}` | Long | Errors / alerts (logged, not sent to Telegram) |
| `/runs/{run_id}/original` | 7 days | Original user request for this pipeline run |
| `/runs/{run_id}/step-{n}/output` | 7 days | Full output of pipeline step N |
| `/runs/{run_id}/scratch` | 7 days | Shared notepad — all agents in the run can read/write |
| `/research`, `/wiki` | Long | Shared read-only reference context |
| `/skills/` | Long | *(planned)* Shared skill knowledge blocks |

#### Permission Model

Agents declare `read` and `write` path prefix lists in their manifest. The KB client enforces these on every operation. Two exceptions:

- **`/runs/`** — always readable and writable by all agents regardless of manifest (all pipeline agents need shared run data without per-manifest configuration)
- **Coordinator** — has full access with no permission checks (passes `permissions=None`)

`get_unchecked(scope)` bypasses permission checks entirely — used by the agent runtime to read coordinator-written `context_injection` scopes on startup.

#### Scratch Space

All agents in a pipeline share a scratch record at `/runs/{run_id}/scratch`. Two tools are auto-injected for pipeline agents:

- **`scratch_read`** — returns current scratch content (or `"(scratch is empty)"`)
- **`scratch_write`** — overwrites scratch entirely; include anything you want to preserve

Scratch uses direct asyncpg connections (no KB client permission layer). Both tools open and close a connection per call. Overwrite semantics — last write wins — so scratch is best for coordination flags and mid-run notes, not full data dumps. Full step output is in `/runs/{run_id}/step-{n}/output` and doesn't get overwritten.

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

## Pipelines

### How Context Flows Between Steps

Context does **not** travel through Argo Workflow arguments — Argo only carries a tiny `instruction` string. All real context lives in the KB under `/runs/{run_id}/`.

Before the first LLM call, each pipeline agent receives a structured framing block prepended to its user message:

```
You are one step in a multi-step pipeline. Workflow: <name>.
Your role in this step: <step description from workflow editor>

---

The original user request — stay aligned with this throughout:
<content of /runs/{run_id}/original>

---

[CONTEXT: STEP-0/OUTPUT]
<content of /runs/{run_id}/step-0/output>

---

<current step instruction>
```

This means every agent in a pipeline always sees:
1. The original user request verbatim (no telephone effect)
2. The immediately prior step's full output (no coordinator-side truncation)
3. Its specific role in the pipeline

The coordinator writes each completed step's output to `/runs/{run_id}/step-{n}/output` (7-day TTL) before launching the next step. These scopes are passed in `context_injection` in the task config.

### Research Pipeline (built-in)

Two-phase orchestration for `research-regular` and `research-deep` workflows:

```
Phase 1: GATHERER
  ├── web_search via SearXNG
  ├── web_read (crawl4ai → trafilatura → markdownify → basic)
  │   └── Pages >5000 chars summarized by qwen2.5:7b
  ├── wiki_read (Wikipedia REST API)
  └── Output written to /runs/{run_id}/step-0/output (7d TTL)

Coordinator launches Phase 2 with context_injection pointing at both
/runs/{run_id}/original and /runs/{run_id}/gather/output

Phase 2: WRITER
  ├── Receives original brief + full gatherer output in context
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

### Dynamic Pipelines (custom workflows)

Multi-step pipelines defined in the Workflows editor. The coordinator:

1. Generates a `run_id` and writes the original brief to `/runs/{run_id}/original` (7d TTL)
2. Creates `/runs/{run_id}/scratch` (empty, 7d TTL) for shared agent notepad
3. Launches step 0 with `context_injection: [original_scope]`
4. Waits for each step to complete, mirrors output to `/runs/{run_id}/step-{n}/output`
5. Launches next step with `context_injection: [original_scope, step-n/output]`

Each step's task config also carries `scratch_scope` so the runner auto-injects `scratch_read`/`scratch_write` tools.

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
| `kb` (pipeline only) | scratch_read, scratch_write | Auto-injected for all pipeline agents with a `scratch_scope` |

Tool schemas are versioned in agent-kb (`tool_schemas` table) with CRUD API at `/api/tools/schemas`.

## Agent Studio UI

Web interface at `mycroft.amer.dev`. Six tabs:

### Test Runner

Submit tasks and watch them execute live.

- **Runner toggle** — Mycroft (default) or Forge
- **Workflow select** — `research-quick`, `research-regular`, `research-deep`, `coder`, or any custom pipeline
- **Advanced options** — max_tokens, temperature, max_iterations, per-phase model overrides, tool allowlist, system prompt override
- **Trace sub-tab** — live collapsible cards for every tool call, LLM response, and system prompt as the task runs
- **Tasks sub-tab** — list recent tasks with status badges; click to open conversation panel; cross-links to reports

### Agents

Create and edit agent definitions without touching the repo.

- Model, max iterations, memory/CPU resource requests
- System prompt editor
- **Permissions & Tools** — tool group checkboxes (web, files, git, github, shell) plus extra individual tools; read/write KB path lists
- Raw `manifest.yaml` and `prompts.py` editors
- Clone agent, delete agent
- **Test Agent** panel — run the agent in isolation with a custom instruction

Changes saved to agent-kb; the coordinator picks them up immediately.

### Workflows

Build multi-step pipelines (custom research flows, chained agent sequences).

Per-step configuration:

| Field | Purpose |
|---|---|
| **Step Description** | Why this step exists — injected into the agent's pipeline framing so it knows its role |
| Agent | Which agent type runs this step |
| Model Override | Override the agent's default model for this step |
| Max Iter | Cap iterations for this step only |
| Tools Override | Comma-separated tool list; replaces agent defaults |
| **System Prompt Suffix** | Appended to the agent's default system prompt — use for output format rules or step-specific constraints without replacing the full prompt |
| **⚠ System Prompt Override** | Replaces the agent's entire system prompt — use sparingly; agent loses all default behavior |

- Add/reorder/remove steps
- Run or Test (2-iteration quick run) directly from the editor
- **Run history** — recent executions with timing and status

### Tools

Manage tool schemas in OpenAI function-calling format.

- Create, edit, delete tool schemas
- Semver labels + integer DB version auto-increment on each save
- Changelog field per version
- Full version history

### Reports

Browse AI-generated research reports.

- Markdown-rendered or raw view toggle
- Metadata: workflow tier, models used, build SHA, creation date
- **View trace ↗** — one click to jump to the Test Runner Trace sub-tab showing the full system prompt, tool calls, and LLM responses that produced the report
- Mobile: toggle bar to switch between report list and detail view

### Logs

Live coordinator log stream.

- Auto-refreshes every 3 seconds while the tab is active
- **Filters:** log level (DEBUG/INFO/WARNING/ERROR), logger name prefix, free text search
- Color-coded by level, auto-scroll to newest
- Reads from `/api/logs` (in-memory 2000-record ring buffer in coordinator)

## Images

Built multi-arch (amd64 + arm64) on every push to `main`:

| Image | Purpose | Size |
|---|---|---|
| `amerenda/mycroft:agent-base-{tag}` | Shared base — Python deps, tools, runtime | ~300MB |
| `amerenda/mycroft:agent-coder-{tag}` | Extends base — Node.js, gh CLI, pytest | ~400MB |
| `amerenda/mycroft:agent-researcher-{tag}` | Extends base — crawl4ai, Playwright, trafilatura | ~1GB |
| `amerenda/mycroft:coordinator-{tag}` | Coordinator service | ~500MB |
| `amerenda/mycroft:frontend-{tag}` | Agent Studio nginx SPA | ~30MB |

## API Reference

Key coordinator endpoints:

```
POST   /api/tasks                     submit a task
GET    /api/tasks                     list tasks (agent_type, status, limit filters)
GET    /api/tasks/{id}                get task
GET    /api/tasks/{id}/conversation   full conversation (messages + tool calls)
GET    /api/tasks/{id}/pipeline       all tasks in the same pipeline chain
POST   /api/tasks/{id}/cancel         cancel running task
DELETE /api/tasks/{id}                delete task

GET    /api/events                    SSE stream — task_update and report_saved events

GET    /api/logs                      coordinator log buffer
                                      ?level=INFO&logger=coordinator&q=text&since=ts&limit=500

GET    /api/reports                   list reports
GET    /api/reports/{id}              get report
DELETE /api/reports/{id}              delete report

GET    /api/agents                    list agents (from DB)
GET    /api/agents/{name}             get agent manifest + prompts
PUT    /api/agents/{name}             save agent

GET    /api/workflows                 list workflows
PUT    /api/workflows/{name}          save workflow (with pipeline_json)
GET    /api/workflows/{name}/runs     recent task runs for a workflow

GET    /api/tools/schemas             list tool schemas
PUT    /api/tools/schemas/{name}      upsert schema (auto-increments DB version)

GET    /api/kb/children               list KB path children
GET    /api/kb/entry?path=            get KB record at exact scope
PUT    /api/kb/entry                  write/replace KB record
DELETE /api/kb/entry?path=            delete records at scope
DELETE /api/kb/subtree?path=          delete all records under prefix

GET    /api/models                    proxy to llm-manager model list
```

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
