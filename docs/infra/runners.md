# GitHub Actions Runners

Two types of runners handle CI across all `amerenda` repos: **mac-mini self-hosted runners** (arm64) and **ARC runners on k3s** (amd64). Every repo that builds and pushes Docker images targets both, creating multi-arch manifests.

## Architecture

```
Mac Mini (arm64)                       murderbot / k3s (amd64)
┌──────────────────────────┐           ┌──────────────────────────────────┐
│  docker-compose runners  │           │  ARC Controller (arc-systems)    │
│                          │           │  ┌────────────────────────────┐  │
│  image: myoung34/        │           │  │  Helm chart v0.13.0        │  │
│  github-runner:noble     │           │  │  authenticates via         │  │
│                          │           │  │  GitHub App (BWS)          │  │
│  labels:                 │           │  └────────────────────────────┘  │
│  self-hosted,arm64,      │           │                                  │
│  docker,mac-mini         │           │  ARC Runner Scale Sets           │
│                          │           │  (one namespace per repo)        │
│  secrets via:            │           │  minRunners: 0 / maxRunners: 3   │
│  /etc/komodo/runner-     │           │  runs-on: arc-runner-set         │
│  secrets (Komodo)        │           │                                  │
└──────────────────────────┘           └──────────────────────────────────┘
```

Secrets flow: **BWS → ExternalSecret → k8s Secret → runner env vars**

## Mac Mini Runners

Managed as a docker-compose stack in the `mac-mini-compose` repo under `runners/`.

Each runner is a separate compose service targeting one repo:

| Service | Repo |
|---------|------|
| `runner-k3s-runners` | `amerenda/k3s-runners` |
| `runner-ecdysis` | `amerenda/ecdysis` |
| `runner-llm-manager` | `amerenda/llm-manager` |
| `runner-llm-agents` | `amerenda/llm-agents` |
| `runner-mycroft` | `amerenda/mycroft` |
| `runner-wikimedia` | `amerenda/wikimedia` |

All services share the same base config (`x-runner-common`):

- Image: `myoung34/github-runner:ubuntu-noble`
- Docker socket mounted for builds
- Secrets injected from `/etc/komodo/runner-secrets` (managed by Komodo)
- Entrypoint wrapper reads secrets from files and exports them as env vars

**Secrets available to mac-mini runners:**

| Secret file | Env var | Purpose |
|-------------|---------|---------|
| `github-app-arc-id` | `APP_ID` | GitHub App ID for registration |
| `github-app-arc-private-key` | `APP_PRIVATE_KEY` | GitHub App private key |
| `docker-hub-k3s-runner-api-key` | `DOCKERHUB_TOKEN` | Docker Hub push access |
| `github-pat-k3s-dean-gitops` | `GITOPS_PAT` | GitOps repo write access |

## ARC Runners (k3s)

Managed via the `k3s-dean-gitops` GitOps repo under `infra/arc-runners-*/`.

### Controller

One ARC controller runs in `arc-systems`, deployed via Helm. It watches all runner scale set namespaces and manages ephemeral runner pods.

- Helm chart: `ghcr.io/actions/gha-runner-scale-set-controller`
- GitHub App credentials sourced from BWS via ExternalSecret into `controller-manager` secret

### Runner Scale Sets

Two categories of scale set:

**Build runners** (Docker socket mounted, pinned to `murderbot`):

| Namespace | Repo |
|-----------|------|
| `arc-runners-ecdysis` | `amerenda/ecdysis` |
| `arc-runners-k3s-runners` | `amerenda/k3s-runners` |
| `arc-runners-llm-manager` | `amerenda/llm-manager` |
| `arc-runners-llm-agents` | `amerenda/llm-agents` |

**CI-only runners** (no Docker, can schedule anywhere):

| Namespace | Repo |
|-----------|------|
| `arc-runners` | `amerenda/k3s-dean-gitops` |
| `arc-runners-mycroft` | `amerenda/mycroft` |
| `arc-runners-tailscale-acl` | `amerenda/tailscale-acl` |
| `arc-runners-wikimedia` | `amerenda/wikimedia` |

All scale sets use `runs-on: arc-runner-set` in workflows (the scale set name is `arc-runner-set` in every namespace). They scale from 0 to 3 replicas.

### Secrets

Each scale set namespace has two ExternalSecrets:

1. **`controller-manager`** — GitHub App credentials (same BWS keys across all namespaces):
    - `github-app-arc-id`
    - `github-app-arc-installation-id`
    - `github-app-arc-private-key`

2. **`runner-ci-credentials`** — CI credentials specific to the repo (e.g., `DOCKERHUB_TOKEN`, `GITOPS_PAT`, or repo-specific API keys)

## Adding a New Runner

### For a new repo that needs CI only (no Docker builds)

1. Create `infra/arc-runners-{repo}/` in `k3s-dean-gitops` with two files:

    **`values.yaml`:**
    ```yaml
    githubConfigUrl: "https://github.com/amerenda/{repo}"
    runnerScaleSetName: arc-runner-set
    githubConfigSecret: controller-manager
    minRunners: 0
    maxRunners: 3
    template:
      spec:
        containers:
          - name: runner
            image: ghcr.io/actions/actions-runner:latest
            env:
              - name: MY_SECRET
                valueFrom:
                  secretKeyRef:
                    name: runner-ci-credentials
                    key: MY_SECRET
    namespaceOverride: arc-runners-{repo}
    ```

    **`externalsecret.yaml`:**
    ```yaml
    ---
    apiVersion: external-secrets.io/v1
    kind: ExternalSecret
    metadata:
      name: controller-manager
      annotations:
        argocd.argoproj.io/sync-wave: "0"
    spec:
      refreshInterval: 1h
      secretStoreRef:
        name: bitwarden-secretstore
        kind: ClusterSecretStore
      target:
        name: controller-manager
        creationPolicy: Owner
      data:
      - secretKey: github_app_id
        remoteRef:
          key: github-app-arc-id
          property: github_app_id
      - secretKey: github_app_installation_id
        remoteRef:
          key: github-app-arc-installation-id
          property: github_app_installation_id
      - secretKey: github_app_private_key
        remoteRef:
          key: github-app-arc-private-key
          property: github_app_private_key
    ---
    apiVersion: external-secrets.io/v1
    kind: ExternalSecret
    metadata:
      name: runner-ci-credentials
      annotations:
        argocd.argoproj.io/sync-wave: "0"
    spec:
      refreshInterval: 1h
      secretStoreRef:
        name: bitwarden-secretstore
        kind: ClusterSecretStore
      target:
        name: runner-ci-credentials
        creationPolicy: Owner
      data:
      - secretKey: MY_SECRET
        remoteRef:
          key: my-bws-secret-name
          property: password
    ```

2. Add the new app to the ArgoCD ApplicationSet (or it's auto-discovered if using directory-based ApplicationSet).

3. In the repo's workflow, use:
    ```yaml
    runs-on: arc-runner-set
    ```

### For a new repo that needs Docker builds

Same as above, plus:

- Add `nodeSelector: { kubernetes.io/hostname: murderbot }` to pin to the x86 worker
- Add `supplementalGroups: [989]` to the pod security context (docker group on murderbot)
- Mount `/var/run/docker.sock` as a `hostPath` volume
- Set `DOCKER_HOST: unix:///var/run/docker.sock` env var on the runner container
- Add `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` to the ExternalSecret and runner env

### For a new arm64 mac-mini runner

1. Add a new service to `mac-mini-compose/runners/compose.yaml` following the `x-runner-common` pattern:
    ```yaml
    runner-{repo}:
      <<: *runner-common
      environment:
        <<: *runner-env
        REPO_URL: https://github.com/amerenda/{repo}
        RUNNER_NAME: mac-mini-{repo}
    ```
2. Deploy via Komodo (no restart needed — `docker compose up -d` picks up the new service).

## How Registration Works

Both runner types authenticate using the same **GitHub App** (`amerenda-arc`):

1. The runner (or ARC controller) reads the App ID and private key
2. It generates a JWT, exchanges it for an installation token via the GitHub API
3. The token is used to register the runner against the target repo
4. For ARC, the controller manages this lifecycle automatically; runners are ephemeral per-job

The GitHub App must have the `Actions: Read & Write` permission on the target repos. Installation IDs are per-org or per-repo — check `github-app-arc-installation-id` in BWS.
