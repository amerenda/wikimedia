import re

import markdown


def _mermaid_pre_format(source, language, class_name, options, md, **kwargs):
    return f'<pre class="mermaid">{source}</pre>'


def markdown_to_html(body: str) -> str:
    md = markdown.Markdown(
        extensions=[
            "pymdownx.superfences",
            "pymdownx.highlight",
            "pymdownx.inlinehilite",
            "admonition",
            "pymdownx.details",
            "attr_list",
            "md_in_html",
        ],
        extension_configs={
            "pymdownx.superfences": {
                "custom_fences": [
                    {
                        "name": "mermaid",
                        "class": "mermaid",
                        "format": _mermaid_pre_format,
                    }
                ]
            },
            "pymdownx.highlight": {
                "anchor_linenums": True,
            },
        },
    )
    html = md.convert(body)
    return _rewrite_internal_md_links(html)


def _rewrite_internal_md_links(html: str) -> str:
    def repl(m: re.Match) -> str:
        href = m.group(1)
        if href.startswith(("http://", "https://", "mailto:", "#", "/wiki/")):
            return m.group(0)
        path = href.split("#", 1)[0]
        frag = href[len(path) :] if "#" in href else ""
        if not path.endswith(".md"):
            return m.group(0)
        target = f"/wiki/{path}"
        return f'href="{target}{frag}"'

    return re.sub(r'href="([^"]+)"', repl, html)
