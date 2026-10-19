"""Builds the public website (docs/) — feed, change pages with receipts, watch list, RSS and a JSON API."""

from __future__ import annotations

import difflib
import html
import json
import shutil
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import store
from .config import Paths, load_services, load_site
from .differ import word_diff_html
from .flags import RADAR

TEMPLATES = Path(__file__).parent / "templates"
TAG_LABELS = {tag: label for tag, (label, _) in RADAR.items()} | {"cosmetic": "Cosmetic", "other": "Other"}
GENERATED = ["index.html", "watched.html", "feed.xml", "c", "api", ".nojekyll"]


def _when(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _pair_lines(old: list[str], new: list[str]) -> list[dict]:
    """Match up old/new paragraphs that are versions of each other, so we can show word-level edits."""
    rows, used = [], set()
    pending_old = list(enumerate(old))
    for n_line in new:
        best, best_ratio = None, 0.45
        for i, o_line in pending_old:
            if i in used:
                continue
            r = difflib.SequenceMatcher(a=o_line, b=n_line, autojunk=False).quick_ratio()
            if r > best_ratio:
                best, best_ratio = i, r
        if best is None:
            rows.append({"old": None, "new": html.escape(n_line)})
        else:
            used.add(best)
            o_html, n_html = word_diff_html(old[best], n_line)
            rows.append({"old": o_html, "new": n_html})
    removed = [{"old": html.escape(o), "new": None} for i, o in enumerate(old) if i not in used]
    return removed + rows


def render_receipts(hunks: list[dict]) -> list[dict]:
    blocks = []
    for h in hunks:
        if h["kind"] == "added":
            rows = [{"old": None, "new": html.escape(line)} for line in h["new"]]
        elif h["kind"] == "removed":
            rows = [{"old": html.escape(line), "new": None} for line in h["old"]]
        else:
            rows = _pair_lines(h["old"], h["new"])
        blocks.append({"kind": h["kind"], "rows": rows})
    return blocks


def build(root: Path, services_file: Path) -> Path:
    paths = Paths(root)
    site = load_site(services_file)
    services = load_services(services_file)
    changes = store.load_changes(paths)
    status = store.load_status(paths)
    out = paths.site
    out.mkdir(parents=True, exist_ok=True)
    for name in GENERATED:  # leave CNAME and anything hand-made alone
        target = out / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "xml"]))
    env.filters["nice_date"] = lambda iso: _when(iso).strftime("%b %-d, %Y")
    env.filters["tag_label"] = lambda t: TAG_LABELS.get(t, t)

    for c in changes:
        c["receipts"] = render_receipts(c.get("hunks", []))
        c["history_url"] = (
            f"{site['repo']}/commits/{site['branch']}/snapshots/{c['service']}/{c['doc']}.md" if site["repo"] else ""
        )
        c["page"] = f"c/{c['id']}.html"
        c["abs_url"] = f"{site['url']}/{c['page']}" if site["url"] else ""

    tag_counts: dict[str, int] = {}
    for c in changes:
        for t in c.get("tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    tags = sorted(tag_counts.items(), key=lambda kv: -kv[1])

    watched = []
    for svc in services:
        docs = []
        for d in svc.documents:
            st = status.get(f"{svc.id}/{d.type}", {})
            docs.append({"label": d.label, "url": d.url, "status": st.get("status", "pending"),
                         "last_checked": st.get("last_checked"), "last_changed": st.get("last_changed"),
                         "error": st.get("error")})
        watched.append({"name": svc.name, "id": svc.id, "docs": docs})
    n_docs = sum(len(s.documents) for s in services)
    last_run = max((s.get("last_checked", "") for s in status.values()), default="") or None

    common = {"site": site, "n_services": len(services), "n_docs": n_docs, "n_changes": len(changes),
              "last_run": last_run, "spicy": sum(1 for c in changes if c.get("sideeye", 0) >= 3)}

    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "index.html").write_text(
        env.get_template("index.html").render(**common, root="", changes=changes, tags=tags), encoding="utf-8")
    (out / "watched.html").write_text(
        env.get_template("watched.html").render(**common, root="", watched=watched), encoding="utf-8")

    (out / "c").mkdir()
    tpl = env.get_template("change.html")
    for c in changes:
        (out / c["page"]).write_text(tpl.render(**common, root="../", c=c), encoding="utf-8")

    for c in changes:
        c["rfc822"] = format_datetime(_when(c["detected_at"]))
    (out / "feed.xml").write_text(
        env.get_template("feed.xml").render(**common, changes=changes[:50]), encoding="utf-8")

    # A tiny public API so other people can build on the data.
    (out / "api").mkdir()
    public = [{k: v for k, v in c.items() if k not in ("hunks", "receipts", "rfc822")} for c in changes]
    (out / "api" / "changes.json").write_text(json.dumps(public, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "api" / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"site: {len(changes)} changes, {n_docs} watched documents → {out}")
    return out
