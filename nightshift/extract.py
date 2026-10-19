"""Turns a messy HTML page into clean policy text: one paragraph per line, no nav, no cookie banner."""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

try:
    import trafilatura
except ImportError:  # pragma: no cover
    trafilatura = None

ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
SPACES = re.compile(r"[ \t ]+")
NOISE_TAGS = ["script", "style", "noscript", "svg", "nav", "header", "footer", "form", "button", "iframe"]
BLOCK_TAGS = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "dt", "dd", "blockquote", "pre"]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = ZERO_WIDTH.sub("", text)
    lines = []
    for line in text.splitlines():
        line = SPACES.sub(" ", line).strip()
        if line:
            lines.append(line)
    # Collapse exact consecutive duplicates (common with responsive menus)
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return "\n".join(out).strip() + "\n"


def _blocks_from_soup(node) -> str:
    for tag in node.find_all(NOISE_TAGS):
        tag.decompose()
    parts = []
    blocks = node.find_all(BLOCK_TAGS)
    if blocks:
        for b in blocks:
            # Skip containers whose text is already covered by a nested block
            if b.find(BLOCK_TAGS):
                continue
            t = b.get_text(" ", strip=True)
            if t:
                prefix = "#" * int(b.name[1]) + " " if re.fullmatch(r"h[1-6]", b.name) else ""
                parts.append(prefix + t)
    else:
        parts.append(node.get_text("\n", strip=True))
    return "\n".join(parts)


def extract_text(html: str, selector: str | None = None, url: str | None = None) -> str:
    soup = BeautifulSoup(html, "html.parser")

    if selector:
        node = soup.select_one(selector)
        if node is None:
            raise ValueError(f"selector '{selector}' matched nothing")
        return normalize(_blocks_from_soup(node))

    text = None
    if trafilatura is not None:
        text = trafilatura.extract(
            html,
            url=url,
            favor_recall=True,
            include_tables=True,
            include_comments=False,
            include_formatting=True,
            output_format="markdown",
            deduplicate=False,
        )

    fallback_node = soup.find("main") or soup.find("article") or soup.body or soup
    fallback = normalize(_blocks_from_soup(fallback_node))

    # Trafilatura is great at stripping junk but sometimes drops half a long legal page.
    # Keep whichever version holds clearly more of the document.
    if text and len(normalize(text)) >= 0.6 * len(fallback):
        return normalize(text)
    return fallback
