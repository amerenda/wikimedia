# Wikimedia (Homelab Wiki)

FastAPI app that serves internal homelab documentation: Markdown pages live in
`docs/`, are imported into PostgreSQL, and are rendered as HTML with navigation.
MkDocs config in `mkdocs.yml` is also bundled for optional static builds.

## What it does

- **Runtime**: `server/main.py` — reads `wiki_pages` from Postgres, renders with Jinja2, converts Markdown via `pymdown-extensions`.
- **Content**: `docs/` — infra, apps, and runbooks (see `docs/index.md`).
- **Import**: `scripts/import_from_repo.py` — loads `docs/` into the database (paths, nav metadata, bodies).
- **Deploy**: Docker image (`Dockerfile`); cluster manifests live in [`k3s-dean-gitops`](https://github.com/amerenda/k3s-dean-gitops) under `apps/wikimedia/`.

## Requirements

Python dependencies are pinned in `requirements.txt`:

- FastAPI, Uvicorn
- `psycopg` (PostgreSQL)
- Jinja2, PyYAML
- Markdown + pymdown-extensions (Markdown rendering)

## Local / Mac Mini Compose

1. Copy `.env.example` to `.env` and set `DATABASE_URL` (and optional `WIKI_SITE_NAME`).
2. Ensure the `mac-mini-shared` Docker network exists (same pattern as other Mini stacks).
3. Run:

```bash
docker compose up -d --build
```

Default mapping in `compose.yaml`: host `8765` → container `8000`. Health: `GET /health`.

## Importing or refreshing content

From a machine that can reach the wiki database:

```bash
export DATABASE_URL=postgresql://wikimedia:…@<host>:5432/wikimedia
python scripts/import_from_repo.py
```

The container sets `WIKIMEDIA_REPO_ROOT` to `/app/repo` (bundled `docs/` + `mkdocs.yml`). Override when importing from a checkout if needed.

## Optional static site

`mkdocs build` still produces a static site from `docs/` if you want HTML without the app — see comments in `mkdocs.yml`.

## Related repos

- **GitOps**: `k3s-dean-gitops/apps/wikimedia/`
- **Broader stack docs**: content under `docs/infra/` links to k3s, Komodo, app-factory, etc.
