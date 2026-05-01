import os
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from server.db import apply_schema, get_dsn
from server.render import markdown_to_html

_templates = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_schema()
    yield


app = FastAPI(title="Homelab Wiki", lifespan=lifespan)


def _load_nav() -> list[dict]:
    with psycopg.connect(get_dsn()) as conn:
        cur = conn.execute(
            """
            SELECT path, nav_label, nav_section, sort_order
            FROM wiki_pages
            ORDER BY sort_order, path
            """
        )
        rows = cur.fetchall()
    section_order: list[str] = []
    sections: dict[str, list[dict]] = {}
    for path, nav_label, nav_section, sort_order in rows:
        sec = nav_section or ""
        if sec not in sections:
            section_order.append(sec)
            sections[sec] = []
        sections[sec].append({"path": path, "label": nav_label, "sort_order": sort_order})
    return [{"name": name, "pages": sections[name]} for name in section_order]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return RedirectResponse("/wiki/index.md", status_code=302)


@app.get("/wiki/{page_path:path}", response_class=HTMLResponse)
def wiki_page(request: Request, page_path: str):
    if not page_path.endswith(".md"):
        page_path = f"{page_path}.md"
    with psycopg.connect(get_dsn()) as conn:
        cur = conn.execute(
            """
            SELECT title, body, nav_label, nav_section
            FROM wiki_pages WHERE path = %s
            """,
            (page_path,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Page not found")
    title, body, nav_label, nav_section = row
    html_content = markdown_to_html(body)
    nav = _load_nav()
    tpl = _templates.get_template("page.html")
    return tpl.render(
        request=request,
        site_name=os.environ.get("WIKI_SITE_NAME", "Homelab Wiki"),
        page_title=title,
        nav_label=nav_label,
        nav_section=nav_section,
        content=html_content,
        nav=nav,
        current_path=page_path,
    )
