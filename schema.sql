-- Applied automatically on wiki server startup (idempotent).
CREATE TABLE IF NOT EXISTS wiki_pages (
    path text PRIMARY KEY,
    title text NOT NULL,
    body text NOT NULL,
    nav_section text NOT NULL DEFAULT '',
    nav_label text NOT NULL DEFAULT '',
    sort_order integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS wiki_pages_section_order_idx
    ON wiki_pages (nav_section, sort_order, path);
