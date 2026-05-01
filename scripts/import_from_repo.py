#!/usr/bin/env python3
"""Load mkdocs.yml nav + docs/*.md into Postgres (upsert)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import yaml

REPO_ROOT = Path(os.environ.get("WIKIMEDIA_REPO_ROOT", Path(__file__).resolve().parent.parent))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.db import apply_schema  # noqa: E402


def _walk_nav(items: list, section: str = "") -> list[tuple[str, str, str]]:
    """Return (path, nav_label, nav_section) in nav order."""
    out: list[tuple[str, str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, val in item.items():
            if isinstance(val, str):
                out.append((val, key, section))
            elif isinstance(val, list):
                out.extend(_walk_nav(val, key))
    return out


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    apply_schema()

    mkdocs_path = REPO_ROOT / "mkdocs.yml"
    docs_dir = REPO_ROOT / "docs"
    if not mkdocs_path.is_file():
        print(f"Missing {mkdocs_path}", file=sys.stderr)
        return 1

    cfg = yaml.safe_load(mkdocs_path.read_text())
    nav = cfg.get("nav") or []
    entries = _walk_nav(nav)

    with psycopg.connect(dsn) as conn:
        for sort_order, (rel, label, section) in enumerate(entries):
            path = rel.replace("\\", "/")
            src = docs_dir / path
            if not src.is_file():
                print(f"skip missing file: {src}", file=sys.stderr)
                continue
            body = src.read_text()
            title = label
            conn.execute(
                """
                INSERT INTO wiki_pages (path, title, body, nav_section, nav_label, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (path) DO UPDATE SET
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    nav_section = EXCLUDED.nav_section,
                    nav_label = EXCLUDED.nav_label,
                    sort_order = EXCLUDED.sort_order,
                    updated_at = now()
                """,
                (path, title, body, section, label, sort_order),
            )
        conn.commit()

    print(f"Imported {len(entries)} nav entries from {mkdocs_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
