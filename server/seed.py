"""Seed wiki_pages from mkdocs nav + docs/ (used on first boot and by import script)."""
from __future__ import annotations

from pathlib import Path

import psycopg
import yaml

from server.db import get_dsn


def walk_nav(items: list, section: str = "") -> list[tuple[str, str, str]]:
    """Return (path, nav_label, nav_section) in nav order."""
    out: list[tuple[str, str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, val in item.items():
            if isinstance(val, str):
                out.append((val, key, section))
            elif isinstance(val, list):
                out.extend(walk_nav(val, key))
    return out


def import_from_repo(repo_root: Path) -> int:
    """Upsert all pages from repo_root (contains mkdocs.yml + docs/). Returns rows written."""
    mkdocs_path = repo_root / "mkdocs.yml"
    docs_dir = repo_root / "docs"
    if not mkdocs_path.is_file():
        raise FileNotFoundError(f"Missing {mkdocs_path}")
    cfg = yaml.safe_load(mkdocs_path.read_text())
    nav = cfg.get("nav") or []
    entries = walk_nav(nav)
    dsn = get_dsn()
    count = 0
    with psycopg.connect(dsn) as conn:
        for sort_order, (rel, label, section) in enumerate(entries):
            path = rel.replace("\\", "/")
            src = docs_dir / path
            if not src.is_file():
                continue
            body = src.read_text()
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
                (path, label, body, section, label, sort_order),
            )
            count += 1
        conn.commit()
    return count


def wiki_page_count() -> int:
    with psycopg.connect(get_dsn()) as conn:
        row = conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()
    return int(row[0]) if row else 0


def seed_if_empty(repo_root: Path) -> None:
    """If wiki_pages has no rows, import bundled markdown (k8s / first deploy)."""
    if wiki_page_count() > 0:
        return
    if not (repo_root / "mkdocs.yml").is_file():
        return
    import_from_repo(repo_root)
