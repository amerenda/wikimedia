#!/usr/bin/env python3
"""Load mkdocs.yml nav + docs/*.md into Postgres (upsert)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("WIKIMEDIA_REPO_ROOT", Path(__file__).resolve().parent.parent))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.db import apply_schema  # noqa: E402
from server.seed import import_from_repo  # noqa: E402


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    apply_schema()
    mkdocs_path = REPO_ROOT / "mkdocs.yml"
    if not mkdocs_path.is_file():
        print(f"Missing {mkdocs_path}", file=sys.stderr)
        return 1

    n = import_from_repo(REPO_ROOT)
    print(f"Imported {n} pages from {mkdocs_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
