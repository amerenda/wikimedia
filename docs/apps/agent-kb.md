# Agent KB

The Agent KB is the shared knowledge base and context store for the Mycroft agent platform. It is a PostgreSQL + pgvector database running on the Mac Mini (`agent-kb.amer.dev:5433`, database `agent_kb`), accessed by all agents and the coordinator via the `KBClient` library.

- **Repo:** `amerenda/mycroft` (`common/kb.py`, `common/models.py`)
- **Host:** `agent-kb.amer.dev:5433`
- **Database:** `agent_kb`
- **Table:** `memory_records` (records) + `agent_tasks` (task lifecycle)

---

## What It Does

The KB is the single source of truth for all agent I/O. Agents do not communicate directly — they read and write scoped paths in the KB. The coordinator mediates context between pipeline steps by writing to shared `/runs/` paths.

| Who writes | What they write | Who reads |
|---|---|---|
| Coordinator | Task inbox, original brief, step outputs, scratch | Agent runtime |
| Agent runtime | Conversation history, final result | Coordinator, next pipeline step |
| Tools (scratch_write) | Mid-run notes, partial findings | Any agent in the same run |

---

## Memory Tiers

| Tier | TTL | Scope prefix | Purpose |
|---|---|---|---|
| **Long-term** | Permanent | `/agents/*/results/`, `/tasks/`, `/research/`, `/wiki/` | Task results, conversation history, shared reference knowledge |
| **Short-term** | 7 days | `/runs/{run_id}/` | Pipeline run data — expires automatically after the run is no longer relevant |

Short-term records carry an `expires_at` timestamp. The coordinator runs hourly cleanup (`DELETE WHERE expires_at < NOW()`).

---

## Scope Path Reference

All KB records are addressed by a `/`-delimited scope string. These are the canonical paths:

| Path | TTL | Written by | Read by | Purpose |
|---|---|---|---|---|
| `/agents/{type}/inbox/{task_id}` | Long | Coordinator | Agent runtime (on startup) | Task instruction; rarely read directly now that `context_injection` is used |
| `/tasks/{task_id}/conversation` | Long | Agent runtime | Coordinator, UI | Full JSON conversation history; persisted after each iteration for restart safety |
| `/agents/{type}/results/{task_id}` | Long | Agent runtime | Coordinator | Final agent output; coordinator mirrors this to `/runs/` for the next step |
| `/notifications/alex/{task_id}` | Long | Agent runtime | Coordinator logs | Error alerts and warnings (logged, not sent to Telegram) |
| `/runs/{run_id}/original` | 7 days | Coordinator | All pipeline agents | The original user request verbatim; injected into every step so agents stay aligned |
| `/runs/{run_id}/step-{n}/output` | 7 days | Coordinator | Next pipeline step | Full output of step N, mirrored after completion; no coordinator-side truncation |
| `/runs/{run_id}/gather/output` | 7 days | Coordinator | Research writer phase | Gatherer output for the built-in research pipeline |
| `/runs/{run_id}/scratch` | 7 days | Any pipeline agent | Any pipeline agent | Shared notepad; overwrite semantics (last write wins) |
| `/research`, `/wiki` | Long | Manual / future agents | All agents | Shared read-only reference context available to all agents |
| `/skills/` | Long | *(planned)* | All agents | Shared skill knowledge blocks |

---

## Context Flow Between Pipeline Steps

This is the most important thing to understand when writing agents that run in pipelines.

**Context does NOT travel through Argo Workflow arguments.** Argo only carries a tiny `instruction` string. All real context lives in the KB under `/runs/{run_id}/`.

### What an agent sees at the start of a pipeline step

Before the first LLM call, the agent runtime prepends a structured framing block to the user message:

```
You are one step in a multi-step pipeline. Workflow: <workflow_name>.
Your role in this step: <step description from the Workflows editor>

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

1. **The original user request verbatim** — prevents telephone effect across long chains
2. **The prior step's full output** — no coordinator-side truncation (the coordinator mirrors the full result text before launching the next step)
3. **Its specific role** — from the step description you write in the Workflows editor

### The coordinator's role in context passing

```
Step N completes
    │
    ▼
Coordinator reads /agents/{type}/results/{task_N_id}
    │
    ▼
Writes full content to /runs/{run_id}/step-N/output  (7-day TTL)
    │
    ▼
Creates Step N+1 task with:
  context_injection: [
    "/runs/{run_id}/original",
    "/runs/{run_id}/step-N/output"
  ]
    │
    ▼
Step N+1 agent starts, reads both scopes via get_unchecked()
```

### context_injection

`context_injection` is a list of KB scope paths set in the task config by the coordinator. The agent runtime reads each one with `get_unchecked()` (bypasses permission checks — these are coordinator-written, trusted scopes) and builds them into the framing block.

Pipeline steps always receive at minimum:
- `/runs/{run_id}/original` (step 0) — or additionally `/runs/{run_id}/step-N/output` for subsequent steps

---

## How an Agent Outputs Its Result

An agent's "output" is its **final text response** — the last assistant message before the agent loop ends. The runtime writes this to `/agents/{type}/results/{task_id}`, which the coordinator then reads and mirrors into `/runs/` for the next step.

### What this means for prompt writing

**❌ Wrong — causes agent to call write_file:**
> "Write the complete report out, another agent will check formatting and write it."

The phrase "write out" is ambiguous — the LLM interprets it as a file operation and calls `write_file`, which writes to the pod's local `/workspace/` disk. The coordinator cannot read that file. The next step gets empty context.

**✅ Correct:**
> "Output your complete report as your final response text. Do not call write_file. Your text response is how the next agent receives your output — write the full report directly in this message."

**Or more concisely:**
> "Return your complete findings as your final message. Your response text IS your output — the pipeline passes it directly to the next agent. Do not write to any file."

**Key phrases to use:**
- "your final response text" — makes the output channel explicit
- "do not call write_file" — direct instruction to avoid file tools
- "your response is how the next agent receives your output" — explains the pipeline mechanics

The step description in the Workflows editor is also a good place to reinforce this:
> "Output your full research findings as your response text — no file writes. The next step will format them."

---

## KB Client API

The `KBClient` (`common/kb.py`) is the primary interface for reading and writing KB records.

### Writing

```python
await kb.write(
    scope="/agents/researcher/results/{task_id}",
    content="Full result text...",
    categories=["research", "report"],     # optional, used in semantic search
    metadata={"task_id": task_id},          # arbitrary JSON
    importance=0.7,                         # 0.0–1.0, influences search ranking
    source="researcher/{task_id}",          # who wrote it
    needs_embedding=True,                   # set False for large blobs (saves time)
    ttl_days=7,                             # None = permanent
)
```

### Reading

```python
# Read the most recent record at a scope
record = await kb.get("/agents/researcher/results/{task_id}")
# record.content, record.metadata, record.created_at, etc.

# Read bypassing permission checks (for coordinator-injected context)
record = await kb.get_unchecked("/runs/{run_id}/original")

# Semantic search across a scope prefix
results = await kb.recall(
    query="What is the capital of France?",
    scopes=["/research", "/wiki"],
    limit=5,
)
```

### Upsert (create or overwrite by scope)

```python
await kb.upsert_by_scope(
    scope="/runs/{run_id}/scratch",
    content="Updated notes...",
    source="researcher/{task_id}",
)
```

### Deletion

```python
await kb.delete_by_scope("/runs/{run_id}/scratch")  # exact scope
await kb.delete_subtree("/runs/{run_id}/")           # all records under prefix
```

### Task lifecycle

```python
await kb.create_task(agent_type="researcher", trigger="manual", config={...})
await kb.update_task(task_id, status=TaskStatus.running)
await kb.update_task(task_id, status=TaskStatus.completed, result={"summary": "..."})
task = await kb.get_task(task_id)
# task.status, task.result, task.argo_workflow_name, etc.
```

---

## KB Record Structure

```python
class MemoryRecord(BaseModel):
    id: str                           # UUID
    content: str                      # the actual text
    scope: str                        # e.g. "/agents/researcher/results/abc123"
    categories: list[str] = []        # semantic tags
    metadata: dict[str, Any] = {}     # arbitrary JSON
    importance: float = 0.5           # 0.0–1.0
    source: str | None = None         # who wrote it
    needs_embedding: bool = True      # if true, content is vectorized (384-dim)
    created_at: datetime | None = None
    # expires_at is in the DB but not in the model — set via ttl_days in write()
```

`needs_embedding=False` skips vector generation. Use this for large pipeline context blobs that will always be read by exact scope — semantic search over them isn't useful and embedding is slow.

---

## Permission Model

Agents declare `read` and `write` path prefix lists in their manifest:

```yaml
permissions:
  read:
    - /agents/researcher/inbox
    - /research
    - /wiki
    - /tasks
  write:
    - /agents/researcher/results
    - /agents/coder/inbox
    - /tasks
    - /notifications/alex
```

The KB client enforces these on every operation.

**Two global exceptions:**

1. **`/runs/`** — always accessible to all agents regardless of manifest. This is deliberate: pipeline agents need shared run data without requiring every manifest to list every run path.
2. **Coordinator** — passes `permissions=None` to `KBClient`, bypassing all checks. Only the coordinator runs with full access.

**`get_unchecked(scope)`** bypasses permission checks entirely. The agent runtime uses this specifically to read `context_injection` scopes on startup — these are coordinator-written paths that an agent's manifest might not explicitly list.

---

## Scratch Space

All agents in a pipeline share a scratch record at `/runs/{run_id}/scratch`. Two tools are auto-injected when a task has a `scratch_scope` in its config:

| Tool | What it does |
|---|---|
| `scratch_read` | Returns current scratch content, or `"(scratch is empty)"` |
| `scratch_write` | Overwrites scratch entirely with new content |

**Overwrite semantics** — last write wins. Scratch is best for coordination flags, mid-run notes, and partial findings that don't need to survive the pipeline. Full step output is in `/runs/{run_id}/step-{n}/output` and is never overwritten.

---

## Vector Search

Embeddings use `all-MiniLM-L6-v2` (384-dimensional). Semantic search is available via `kb.recall()` for agents that want to retrieve relevant context from long-term scopes like `/research` or `/wiki`.

Set `needs_embedding=False` for records that will only ever be read by exact scope (pipeline context blobs, conversation history) — this saves embedding time and avoids polluting the vector index with records that won't benefit from similarity search.

---

## Common Pitfalls

### Agent writes to a file instead of outputting text

Symptom: next pipeline step receives `(No output from step N)` or empty context.

Cause: the agent called `write_file` to write its output, which goes to pod-local `/workspace/`. The coordinator reads KB results, not the pod filesystem.

Fix: see [How an Agent Outputs Its Result](#how-an-agent-outputs-its-result) above. Audit the agent's system prompt and step description for any language that implies file output.

### context_injection scopes not readable

Symptom: agent runtime logs `get_unchecked returned None` for an injected scope.

Cause: the coordinator wrote the scope *after* the agent started (race condition), or the scope was never written (bug in pipeline logic).

Fix: the coordinator always writes `/runs/{run_id}/original` before submitting the first step. Step N output is written before step N+1 is launched. If the scope is missing, check coordinator logs for errors in `_run_dynamic_pipeline_steps`.

### Pipeline step shows "completed" but Argo reports failed

The coordinator now makes Argo the source of truth. If Argo reports a workflow failure, the task is marked `failed` regardless of what the agent runtime reported. This handles pods that crash after writing their result but before clean exit.

---

## Explorer API (KB Browser in Agent Studio)

The KB browser in Agent Studio uses these endpoints:

```
GET /api/kb/children?path=/&since_minutes=60   list children of a scope prefix
GET /api/kb/entry?path=/agents/researcher/...  get a specific record
PUT /api/kb/entry                               write/replace a record
DELETE /api/kb/entry?path=...                  delete a record
DELETE /api/kb/subtree?path=...                delete all records under a prefix
GET /api/kb/task/{task_id}                     all KB records associated with a task
GET /api/kb/count                              count of records (optionally filtered)
```
