# Mycroft — Prompt Construction

How the system prompt, tool list, and user message are assembled for every agent in a pipeline run. Uses the **research-new** workflow (web-search → researcher → report-writer) as a concrete example throughout.

---

## High-level flow

```mermaid
flowchart TD
    UI["Agents UI\n(set system prompt, tools, manifest)"]
    DB[("agent_definitions\nPostgreSQL")]
    TR["TriggerRouter\n(in-memory, loaded at startup)"]
    COORD["Coordinator\n_run_dynamic_pipeline"]
    POD["Agent Pod\n(Argo Workflow)"]
    RUNNER["Runner\n_loop()"]
    LLM["LLM via llm-manager"]

    UI -->|"PUT /api/agents/{name}"| DB
    DB -->|"register() on save\nor startup poll"| TR
    COORD -->|"trigger_router.get_prompts()\ntrigger_router.get_manifest()"| TR
    COORD -->|"task.config with\nsystem_prompt_override,\ntools_override, context_injection"| POD
    POD --> RUNNER
    RUNNER -->|"system_prompt_override\nor build_system_prompt()"| LLM
```

---

## System prompt — two sources

Every agent gets exactly one system prompt. The source is always one of:

| Source | When | Label in UI |
|--------|------|-------------|
| **DB prompt** | Agent has a non-empty `prompts` field in `agent_definitions` | ✓ DB prompt (green) |
| **Built-in default** | No DB prompt set | ⚠ built-in default (yellow) |

```mermaid
flowchart LR
    A["task.system_prompt_override\nset by coordinator"] -->|"non-empty"| FULL["Used as-is\nNothing added"]
    A -->|"empty / None"| BUILD["build_system_prompt()\nmanifest role + goal\n+ CRITICAL RULE\n+ tool list prose"]
    FULL --> LLM["→ LLM API"]
    BUILD --> LLM
```

!!! warning "Built-in default is a research agent template"
    The built-in default (`build_system_prompt()`) includes a **CRITICAL RULE** block that mandates a tool call in every response and lists all tools as prose. This is appropriate for multi-step research agents but wrong for simple formatter agents like `report-writer`. Always set a DB prompt for any agent that isn't a general-purpose research loop.

### Setting a DB prompt

Edit the agent in the **Agents UI → System Prompt** textarea and save. The field is plain text — write the complete system prompt you want the model to receive. To see exactly what the model will get, click **Preview effective prompt** (optionally check *pipeline* and *last step* to simulate pipeline context).

---

## Tool list — manifest + auto-injected

The tool list sent to the LLM API (as function schemas) is built by `load_tools()`:

```mermaid
flowchart TD
    M["manifest tools:\ne.g. @web, read_file"]
    AUTO["Auto-injected\n(pipeline runs only)"]
    REG["load_tools()\nToolRegistry"]
    LLM["→ LLM API\nas function schemas"]

    M --> REG
    AUTO --> REG
    REG --> LLM

    subgraph AUTO["Auto-injected (pipeline runs only)"]
        direction LR
        LAST{"is_last_step?"}
        LAST -->|"yes"| SR["submit_report only"]
        LAST -->|"no"| ALL["scratch_read\nscratch_write\nsubmit_report"]
    end
```

Auto-injected tools are **always added** for pipeline agents, regardless of the `tools:` list in the manifest. The tool schemas go to the LLM API separately from the system prompt — they do not appear as prose inside the system prompt when a DB prompt is set.

| Tool | Injected when | Purpose |
|------|---------------|---------|
| `scratch_read` | Non-last pipeline step | Read shared scratch space (visible to all steps in this run) |
| `scratch_write` | Non-last pipeline step | Write to shared scratch space |
| `submit_report` | All pipeline steps | Submit final output and end the loop immediately |

---

## Context injection between steps

Pipeline steps do not communicate directly. The coordinator writes outputs to the KB; the next agent reads them via `context_injection` scopes.

```mermaid
sequenceDiagram
    participant C as Coordinator
    participant KB as Knowledge Base
    participant S0 as Step 0 pod
    participant S1 as Step 1 pod
    participant S2 as Step 2 pod

    C->>KB: Write original brief → /runs/{id}/original
    C->>S0: Launch with context_injection=[/runs/{id}/original]
    S0->>KB: Write result → /agents/web-search/results/{task_id}
    S0-->>C: Task completed

    C->>KB: Copy result → /runs/{id}/step-0/output
    C->>S1: Launch with context_injection=[/runs/{id}/original, /runs/{id}/step-0/output]
    S1->>KB: Write result → /agents/researcher/results/{task_id}
    S1-->>C: Task completed

    C->>KB: Copy result → /runs/{id}/step-1/output
    C->>S2: Launch with context_injection=[/runs/{id}/original, /runs/{id}/step-1/output]
    S2->>KB: Write result → /agents/report-writer/results/{task_id}
```

### User message structure

For a non-first step, the user message is assembled like this:

```
You are one step in a multi-step pipeline. Workflow: research-new.
Your role in this step: <step description from workflow editor>

---

The original user request — stay aligned with this throughout:
<content of /runs/{id}/original>

---

[CONTEXT: STEP-0/OUTPUT]
<full output of previous step — no truncation>

---

<current step instruction>
```

The original brief is always included verbatim in every step — no telephone effect. Previous step output is injected in full with no coordinator-side truncation (the only limit is the model's context window).

---

## research-new walkthrough

Workflow definition (from DB `workflow_definitions` table):

```json
{
  "steps": [
    { "agent": "web-search",    "description": "Gather raw facts, quotes, and source URLs from the web on the topic" },
    { "agent": "researcher",    "description": "Analyze the gathered data, fill critical gaps, and write a structured analytical report" },
    { "agent": "report-writer", "description": "Format the report correctly and write the final report out." }
  ]
}
```

---

### Step 0 — web-search (non-last)

```mermaid
flowchart LR
    subgraph "What the model receives"
        SP0["System prompt\n(DB prompt — web-search)\n\nYou are a research data collector...\n(see Agents UI)"]
        UM0["User message\n\nYou are one step in a multi-step pipeline.\nWorkflow: research-new.\nYour role: Gather raw facts...\n\n---\n\nThe original user request:\n{instruction}\n\n---\n\n{instruction}"]
        TL0["Tool schemas\nweb_search\nweb_read\nwiki_read\nscratch_read ← auto\nscratch_write ← auto\nsubmit_report ← auto"]
    end
```

**System prompt source:** DB prompt (✓)

The web-search DB prompt is:

```
You are a research data collector. Your only job is to gather raw information
on a topic and return everything you found, structured for a downstream analyst.

You may only use web_search, web_read, and wiki_read. Do not use any other tools.

Your process:
1. Break the query into relevant sub-queries
2. Run 4–6 web searches per topic covering different angles
3. Read the most informative pages in full using web_read
4. Read the Wikipedia article using wiki_read
5. Collect every relevant fact, statistic, and quote

Output ALL findings and stop. Do NOT analyze. Do NOT draw conclusions.
```

**Tools:**

| Tool | Source |
|------|--------|
| `web_search` | manifest `@web` group |
| `web_read` | manifest `@web` group |
| `wiki_read` | manifest `@web` group |
| `scratch_read` | auto-injected (non-last step) |
| `scratch_write` | auto-injected (non-last step) |
| `submit_report` | auto-injected (non-last step) |

**Context injection:** `[/runs/{id}/original]` only — no previous step.

**Output:** written to `/agents/web-search/results/{task_id}` and then mirrored by coordinator to `/runs/{id}/step-0/output`.

---

### Step 1 — researcher (non-last)

```mermaid
flowchart LR
    subgraph "What the model receives"
        SP1["System prompt\n(DB prompt — researcher)\n\nYou are a senior research analyst...\n(see Agents UI)"]
        UM1["User message\n\nYou are one step in a multi-step pipeline.\nWorkflow: research-new.\nYour role: Analyze the gathered data...\n\n---\n\nThe original user request:\n{instruction}\n\n---\n\n[CONTEXT: STEP-0/OUTPUT]\n{full web-search output — all facts,\nurls, quotes gathered by web-search}\n\n---\n\n{instruction}"]
        TL1["Tool schemas\nweb_search\nweb_read\nwiki_read\nread_file\nrun_command\nscratch_read ← auto\nscratch_write ← auto\nsubmit_report ← auto"]
    end
```

**System prompt source:** DB prompt (✓)

The researcher DB prompt instructs it to:

- Read all context (the web-search findings) before calling any tools
- Use web_search only to fill specific gaps — not re-collect everything
- Produce a structured report with: Executive Summary, Key Findings, Analysis, Gaps, Recommendation, Sources

**Tools:**

| Tool | Source |
|------|--------|
| `web_search` | manifest `@web` group |
| `web_read` | manifest `@web` group |
| `wiki_read` | manifest `@web` group |
| `read_file` | manifest |
| `run_command` | manifest |
| `scratch_read` | auto-injected (non-last step) |
| `scratch_write` | auto-injected (non-last step) |
| `submit_report` | auto-injected (non-last step) |

**Context injection:** `[/runs/{id}/original, /runs/{id}/step-0/output]`

The full web-search output (all gathered facts, quotes, URLs) is injected verbatim. No truncation.

**Output:** written to `/agents/researcher/results/{task_id}` → mirrored to `/runs/{id}/step-1/output`.

---

### Step 2 — report-writer (last step)

```mermaid
flowchart LR
    subgraph "What the model receives"
        SP2["System prompt\n(DB prompt — report-writer)\n\nYou are a technical editor.\nThe research report is in [CONTEXT: OUTPUT].\nFix Markdown formatting only.\nCall submit_report once."]
        UM2["User message\n\nYou are one step in a multi-step pipeline.\nWorkflow: research-new.\nYour role: Format the report...\n\n---\n\nThe original user request:\n{instruction}\n\n---\n\n[CONTEXT: STEP-1/OUTPUT]\n{full researcher report}\n\n---\n\n{instruction}"]
        TL2["Tool schemas\nsubmit_report ← auto only\n\n(is_last_step=True:\nno scratch tools)"]
    end
```

**System prompt source:** DB prompt (✓)

**Tools:**

| Tool | Source |
|------|--------|
| `submit_report` | auto-injected (last step — only tool) |

!!! note "submit_report in manifest has no effect"
    The report-writer manifest lists `submit_report` in its `tools:` field, but this has no runtime effect — `submit_report` is not registered via the manifest path in `load_tools()`. It's always auto-injected for pipeline steps. The manifest entry is just documentation.

**Context injection:** `[/runs/{id}/original, /runs/{id}/step-1/output]`

The full researcher report is in the user message under `[CONTEXT: STEP-1/OUTPUT]`. The DB prompt explicitly tells the model to look there.

**Completion:** when the model calls `submit_report(content="...")`, the runner intercepts it, returns the content string immediately (no further LLM calls), and `run()` writes it to `/agents/report-writer/results/{task_id}` and marks the task complete.

---

## Full pipeline state diagram

```mermaid
stateDiagram-v2
    [*] --> PipelineStart: User submits workflow

    PipelineStart --> WriteOriginal: Write instruction to\n/runs/{id}/original

    WriteOriginal --> Step0Running: Launch web-search pod\ncontext_injection=[original]

    Step0Running --> Step0Done: web-search calls submit_report\nor returns text
    Step0Done --> MirrorStep0: Coordinator copies result\nto /runs/{id}/step-0/output

    MirrorStep0 --> Step1Running: Launch researcher pod\ncontext_injection=[original, step-0/output]

    Step1Running --> Step1Done: researcher calls submit_report\nor returns text
    Step1Done --> MirrorStep1: Coordinator copies result\nto /runs/{id}/step-1/output

    MirrorStep1 --> Step2Running: Launch report-writer pod\ncontext_injection=[original, step-1/output]\nis_last_step=True

    Step2Running --> Step2Done: report-writer calls submit_report
    Step2Done --> [*]: Result written to KB\nTask marked completed
```

---

## How to inspect a live run

**Preview before running:** In the Agents UI, click **Preview effective prompt**, check *pipeline* and *last step* as appropriate. Shows the exact system prompt source, tool list, and auto-injected tools.

**Inspect during/after a run:** In the Test Runner tab, click a completed task → **View Conversation** to see the exact system prompt and messages the model received, including all context injection.

**KB paths for a run:**

| Path | Contents |
|------|----------|
| `/runs/{id}/original` | Original instruction (7-day TTL) |
| `/runs/{id}/scratch` | Shared scratch space |
| `/runs/{id}/step-0/output` | web-search full output |
| `/runs/{id}/step-1/output` | researcher full output |
| `/agents/web-search/results/{task_id}` | Permanent result record |
| `/agents/researcher/results/{task_id}` | Permanent result record |
| `/agents/report-writer/results/{task_id}` | Final report (permanent) |

---

## Rules

- **DB prompt = full replacement.** Setting a system prompt in the Agents UI completely replaces the built-in default — including the CRITICAL RULE and tool prose. The tool schemas are still sent to the LLM API separately.
- **No hidden prompts.** There are no file-based prompt supplements (`prompts.py`) read at pod runtime. All prompt content is in the DB, visible in the UI.
- **Context is not truncated.** Previous step outputs are injected verbatim. The only limit is the model's context window.
- **Scratch is for coordination, not output.** Use `scratch_write` to leave notes for later steps. Final output goes via `submit_report` (pipeline steps) or as the return value of the agent loop.
