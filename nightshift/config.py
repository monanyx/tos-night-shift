"""Loads services.yaml and knows where everything lives on disk."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DOC_LABELS = {
    "terms": "Terms of Service",
    "privacy": "Privacy Policy",
    "cookies": "Cookie Policy",
    "ai": "AI Terms",
    "community": "Community Guidelines",
    "eula": "End User License Agreement",
}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class Document:
    type: str
    url: str
    render: bool = False          # needs a headless browser (JS-heavy page)
    selector: str | None = None   # CSS selector for the policy body, if auto-extract fails

    @property
    def label(self) -> str:
        return DOC_LABELS.get(self.type, self.type.replace("-", " ").title())


@dataclass
class Service:
    id: str
    name: str
    documents: list[Document] = field(default_factory=list)


@dataclass
class Paths:
    root: Path

    @property
    def snapshots(self) -> Path:
        return self.root / "snapshots"

    @property
    def changes(self) -> Path:
        return self.root / "data" / "changes"

    @property
    def status(self) -> Path:
        return self.root / "data" / "status.json"

    @property
    def site(self) -> Path:
        return self.root / "docs"


def load_site(path: Path) -> dict:
    """Optional `site:` block in services.yaml: title, url (public site URL), repo (GitHub URL)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    site = raw.get("site") or {}
    return {
        "title": site.get("title", "ToS Night Shift"),
        "url": str(site.get("url", "")).rstrip("/"),
        "repo": str(site.get("repo", "")).rstrip("/"),
        "branch": site.get("branch", "main"),
        "demo": bool(site.get("demo", False)),
    }


def load_services(path: Path) -> list[Service]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services: list[Service] = []
    seen: set[str] = set()
    for entry in raw.get("services", []):
        sid = str(entry["id"]).strip()
        if not SLUG_RE.match(sid):
            raise ValueError(f"service id '{sid}' must be lowercase letters, digits and dashes")
        if sid in seen:
            raise ValueError(f"duplicate service id '{sid}'")
        seen.add(sid)
        docs = []
        doc_types: set[str] = set()
        for d in entry.get("documents", []):
            dtype = str(d["type"]).strip()
            if not SLUG_RE.match(dtype):
                raise ValueError(f"{sid}: document type '{dtype}' must be a slug")
            if dtype in doc_types:
                raise ValueError(f"{sid}: duplicate document type '{dtype}'")
            doc_types.add(dtype)
            docs.append(
                Document(
                    type=dtype,
                    url=str(d["url"]).strip(),
                    render=bool(d.get("render", False)),
                    selector=d.get("selector"),
                )
            )
        services.append(Service(id=sid, name=str(entry.get("name", sid)), documents=docs))
    return services
