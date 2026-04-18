# App Factory

Pipeline for deploying new stateless apps to k3s. Handles secrets, databases, k8s manifests, and ArgoCD registration from a single TOML spec.

**Repo:** [`amerenda/app-factory`](https://github.com/amerenda/app-factory)

## Overview

```
apps/myapp.toml ──► make create-app APP=myapp
      │
      ├── validate   (spec checks)
      ├── provision  (OpenTofu: postgres DB + BWS secrets)
      └── generate   (k8s manifests → k3s-dean-gitops)
```

Three repos work together:

| Repo | Role |
|------|------|
| `amerenda/app-factory` | Pipeline — OpenTofu IaC, Jinja2 manifest gen, Makefile |
| `amerenda/app-template` | GitHub template repo — CI/CD skeleton for new app repos |
| `amerenda/k3s-dean-gitops` | Receives generated manifests — ArgoCD deploys from here |

## Creating a New App

### Prerequisites

| Tool | Purpose |
|------|---------|
| `tofu` | OpenTofu — provisions database + secrets |
| `python3` + `jinja2` | Manifest generation |
| `gh` | GitHub CLI — create repo from template |

Environment variables:

```bash
export BWS_ACCESS_TOKEN="..."   # BWS machine account token (read/write)
```

GCS HMAC credentials for the tofu state backend are fetched from BWS automatically by the Makefile.

### Step 1 — Create the app repo

```bash
gh repo create amerenda/my-app --template amerenda/app-template --public --clone
```

Edit `.github/workflows/build.yaml` — search for `TODO` and replace `APP_NAME` with your app name (6 spots).

### Step 2 — Write the spec

```bash
cd app-factory
cp apps/template.toml.example apps/my-app.toml
```

Edit the spec:

```toml
[app]
name = "my-app"
domain = "my-app.amer.dev"

[[components]]
name = "backend"
image = "amerenda/my-app:latest"
port = 8081
replicas = 2
health_path = "/health"
ingress = false

[components.resources.requests]
cpu = "50m"
memory = "64Mi"

[components.resources.limits]
cpu = "200m"
memory = "128Mi"

[[components.env]]
name = "DB_PASSWORD"
secret_ref = { name = "postgres-credentials", key = "password" }

[[components.env]]
name = "DATABASE_URL"
value = "postgres://my-app:$(DB_PASSWORD)@agent-kb.amer.dev:5432/my-app"

[[secrets]]
bws_name = "my-app-postgres-password"
k8s_secret = "postgres-credentials"
k8s_key = "password"
generate = true

[database]
type = "postgres"
name = "my-app"
host = "agent-kb.amer.dev"
extensions = []
password_secret = "my-app-postgres-password"

[uat]
enabled = true
replicas = 1
[uat.resources.requests]
cpu = "25m"
memory = "32Mi"
[uat.resources.limits]
cpu = "100m"
memory = "64Mi"

[cicd]
repo = "amerenda/my-app"
label = "deploy:my-app"
```

See [Spec Reference](#spec-reference) below for all fields.

### Step 3 — Run the pipeline

```bash
make create-app APP=my-app GITOPS_DIR=../k3s-dean-gitops
```

This:

1. **Validates** the spec (naming, references, required fields)
2. **Provisions** via OpenTofu:
    - Generates a 40-char random password
    - Creates a BWS secret for it (+ any other `generate = true` secrets)
    - Creates postgres role + database + extensions on `agent-kb.amer.dev`
3. **Generates** k8s manifests into `k3s-dean-gitops`:
    - `apps/my-app/backend/` — deployment, service, externalsecret
    - `apps/my-app/backend-uat/` — UAT variants
    - `infra/arc-runners-my-app/` — ARC runner scale set
    - Appends ArgoCD Application to `root-app.yaml`
    - Inserts UAT ApplicationSet entry

### Step 4 — Review and push

```bash
cd ../k3s-dean-gitops
git add -A && git diff --cached
git commit -m "feat: add my-app via app-factory"
git push
```

ArgoCD auto-syncs. The namespace is created automatically (`CreateNamespace=true`).

### Step 5 — Install the GitHub App

GitHub → amerenda org → Settings → GitHub Apps → **amerenda-deploy-bot** → add the new repo.

### Step 6 — Push app code

```bash
cd my-app
# write code, ensure /health endpoint exists
git push origin main
```

CI builds images → creates deploy PR → UAT auto-deploys → you merge → prod deploys.

## What Gets Created

| Resource | Location / System |
|----------|-------------------|
| PostgreSQL user + database | Mac Mini postgres (`agent-kb.amer.dev`) |
| BWS secrets | Bitwarden Secrets Manager |
| Deployment + Service (prod) | `k3s-dean-gitops/apps/<app>/<component>/` |
| Deployment + Service (UAT) | `k3s-dean-gitops/apps/<app>/<component>-uat/` |
| ExternalSecret | `k3s-dean-gitops/apps/<app>/<component>/externalsecret.yaml` |
| Ingress + TLS + DNS | `k3s-dean-gitops/apps/<app>/<component>/ingress.yaml` |
| ARC runner scale set | `k3s-dean-gitops/infra/arc-runners-<app>/values.yaml` |
| ArgoCD Application (prod) | `root-app.yaml` |
| UAT ApplicationSet entry | `uat-applicationset.yaml` |

## Makefile Commands

```bash
make create-app APP=x GITOPS_DIR=...   # Full pipeline
make validate APP=x                     # Validate spec only
make provision APP=x                    # OpenTofu apply only
make generate APP=x GITOPS_DIR=...      # Manifest generation only
make destroy-app APP=x GITOPS_DIR=...   # Remove manifests (does not drop DB)
make list-apps                          # List all specs
```

## Spec Reference

### `[app]`

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `name` | yes | — | kebab-case, 3-30 chars |
| `domain` | yes | — | Must end in `.amer.dev` |
| `namespace` | no | `name` | Must match `name` |

### `[[components]]`

| Field | Required | Notes |
|-------|----------|-------|
| `name` | yes | Component name (e.g. `backend`, `frontend`) |
| `image` | yes | Must start with `amerenda/` |
| `port` | yes | 1-65535 |
| `replicas` | yes | Prod replica count |
| `health_path` | yes | Probe path (e.g. `/health`) |
| `ingress` | no | `true` generates Ingress + TLS + DNS |
| `resources` | yes | `.requests.cpu`, `.requests.memory`, `.limits.cpu`, `.limits.memory` |
| `env` | no | List of `{ name, value }` or `{ name, secret_ref: { name, key } }` |

### `[[secrets]]`

| Field | Required | Notes |
|-------|----------|-------|
| `bws_name` | yes | BWS secret name, must start with `<app>-` |
| `k8s_secret` | yes | Kubernetes Secret name (created by ExternalSecret) |
| `k8s_key` | yes | Key within the k8s Secret |
| `generate` | yes | `true` = OpenTofu generates value. `false` = create in BWS manually. |

Multiple entries can share the same `k8s_secret` — they're grouped into one ExternalSecret.

### `[database]`

| Field | Required | Notes |
|-------|----------|-------|
| `type` | yes | Only `postgres` supported |
| `name` | yes | Must match `app.name` |
| `host` | yes | Default: `agent-kb.amer.dev` |
| `extensions` | no | e.g. `["pgcrypto", "vector"]` |
| `password_secret` | yes | Must reference a `[[secrets]]` entry's `bws_name` |

### `[uat]`

| Field | Notes |
|-------|-------|
| `enabled` | `true` to generate UAT manifests |
| `replicas` | UAT replica count (typically 1) |
| `resources` | Same structure as component resources (typically halved) |

UAT deployments automatically: suffix names with `-uat`, mark secret refs `optional: true`, add `ENVIRONMENT=uat` env var.

### `[cicd]`

| Field | Notes |
|-------|-------|
| `repo` | GitHub repo (e.g. `amerenda/my-app`) — used for ARC runner config |
| `label` | PR label (e.g. `deploy:my-app`) — used for UAT ApplicationSet |

## Architecture

### OpenTofu Providers

| Provider | Purpose |
|----------|---------|
| `bitwarden/bitwarden-secrets` | Read/write BWS secrets. Reads postgres admin password, creates app secrets. |
| `cyrilgdn/postgresql` | Creates postgres roles, databases, extensions over the network. |
| `hashicorp/random` | Generates passwords. |

State is stored in GCS (`amerenda-db-backups` bucket) via S3-compatible backend.

### Manifest Generation

Python + Jinja2. Templates in `generate/templates/` match the exact patterns used by existing apps (quiz, vikunja, etc.). The generator reads the TOML spec and writes files to the gitops repo.

Idempotent — re-running skips ArgoCD entries that already exist and overwrites manifest files with identical content.

### Template Repo

[`amerenda/app-template`](https://github.com/amerenda/app-template) is a GitHub template repo containing:

- `.github/workflows/build.yaml` — multi-arch build (amd64 on murderbot, arm64 on Mac Mini) + deploy PR creation
- `Dockerfile` — multi-stage build stub
- `TODO` markers for app-specific customization

The CI workflow follows the [UAT-first deploy pipeline](gitops.md#deploy-pipeline).
