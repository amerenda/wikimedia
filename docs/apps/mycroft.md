# Mycroft

AI agent platform for engineering and personal assistant tasks. Agents run as ephemeral Argo Workflow pods on k3s, orchestrated by a coordinator service.

- **Repo:** `amerenda/mycroft`
- **Debug UI:** `mycroft.amer.dev/debug`
- **Namespace:** `mycroft`

## Architecture

```
Telegram Bot
    │
    ▼
Coordinator (FastAPI :8080)
    ├── Intent classification → task routing
    ├── Task CRUD (PostgreSQL)
    ├── Argo Workflow submission (k8s API)
    └── Status updates → Telegram
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
         │              │
         ▼              ▼
   LLM Manager     Knowledge Base
   (job queue)    (PostgreSQL + pgvector)
```

## Components

### Coordinator

FastAPI service managing the full task lifecycle:

- **Telegram polling** — receives messages, classifies intent, routes to agent type
- **Task management** — CRUD with concurrency limits per agent type
- **Argo submission** — creates `WorkflowTemplate` refs via k8s API, polls for completion
- **Debug UI** — `/debug` — task runner, prompt preview, conversation viewer

### Agent Runtime

Thin loop running inside each ephemeral workflow pod:

1. Read task instruction from KB at `/agents/{type}/inbox/{task_id}`
2. Vector-search KB for relevant context (top 5 results)
3. Build system prompt from agent manifest + tools
4. Iterate: LLM → tool calls → results → persist conversation → repeat
5. Write result to `/agents/{type}/results/{task_id}`

**Iteration limits:** per-manifest max (up to 10), capped globally at 5.
**Resume safety:** conversation persisted to KB after each tool-call round; crashed pods restart from last checkpoint.

### Knowledge Base (KB)

PostgreSQL + pgvector on Mac Mini. All agent I/O goes through scoped paths:

| Path pattern | Purpose |
|---|---|
| `/agents/{type}/inbox/{task_id}` | Task instructions (written by coordinator) |
| `/tasks/{task_id}/conversation` | Conversation history (JSON, persisted each iteration) |
| `/agents/{type}/results/{task_id}` | Final output |
| `/notifications/alex/{task_id}` | Errors / alerts |
| `/research`, `/wiki` | Shared read-only context |

Vector search uses `all-MiniLM-L6-v2` (384-dim). Scoring: `0.5×similarity + 0.3×recency + 0.2×importance`.

### LLM Manager Integration

All inference goes through llm-manager's job queue — agents never call Ollama directly:

1. Submit job to `/api/queue/submit`
2. Poll `/api/queue/jobs/{job_id}` until terminal state (10-min timeout)
3. Parse OpenAI-compatible response (content + tool_calls)

## Agents

### Coder (active)

| Property | Value |
|---|---|
| Default model | `qwen2.5:7b` |
| Max iterations | 10 (capped at 5 globally) |
| Tools | git, github, shell, todo |
| Triggers | Telegram (`intent: engineering`), task_completed from researcher |
| Concurrency | 2 simultaneous tasks |

### Others (Phase 2)

researcher, qa, pr-reviewer, documenter — base image supports all, manifests not yet created.

## Tools

| Group | Tools |
|---|---|
| `git` | clone, checkout-branch, add, commit, push, diff |
| `github` | create-pr, comment |
| `shell` | run-command (bash, 120s timeout) |
| `todo` | list-projects, get-tasks, create-task, update-task (Vikunja) |

## Images

Built multi-arch (amd64 + arm64) on every push to `main`:

| Image | Purpose |
|---|---|
| `amerenda/mycroft:agent-base-{tag}` | Shared base — all Python deps, tools, runtime |
| `amerenda/mycroft:agent-coder-{tag}` | Extends base — adds Node.js, gh CLI, pytest |
| `amerenda/mycroft:coordinator-{tag}` | Coordinator service |

CI builds `agent-base` first (amd64 + arm64 manifest), then agent variants pull from it via `--build-arg BASE_TAG`.

## Deployment

GitOps via ArgoCD. Coordinator runs as a k8s Deployment; agents run as ephemeral Argo Workflow pods.

**UAT:** `coordinator-uat` — auto-deployed on PRs labeled `deploy:mycroft`.
**Prod:** `coordinator` — requires PR approval.

**Secrets** (`mycroft-credentials` ExternalSecret from BWS):

| Secret key | Purpose |
|---|---|
| `kb-dsn` | PostgreSQL connection string |
| `llm-registration-secret` | llm-manager auto-discovery |
| `github-token` | Git/GitHub tool operations |
| `telegram-bot-token` | Bot polling |
| `telegram-chat-id` | Notification target |
| `vikunja-token` | Todo read/write for agents |

## Local Development

```bash
# Coordinator
pip install -r requirements.txt
KB_DSN=postgresql://... LLM_MANAGER_URL=http://localhost:8081 \
  uvicorn coordinator.main:app --port 8080

# Agent (CLI mode — no KB needed)
python -m runtime --agent coder --instruction "add a README to amerenda/foo"

# Preview prompt without running
python -m runtime --agent coder --instruction "..." --dry-run

# Tests
pip install -r requirements-test.txt && python -m pytest tests/ -v
```
