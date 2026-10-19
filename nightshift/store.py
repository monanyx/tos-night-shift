"""Reads and writes snapshots, change records and the status board."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Paths


def snapshot_path(paths: Paths, service_id: str, doc_type: str) -> Path:
    return paths.snapshots / service_id / f"{doc_type}.md"


def read_snapshot(paths: Paths, service_id: str, doc_type: str) -> str | None:
    p = snapshot_path(paths, service_id, doc_type)
    return p.read_text(encoding="utf-8") if p.exists() else None


def write_snapshot(paths: Paths, service_id: str, doc_type: str, text: str) -> None:
    p = snapshot_path(paths, service_id, doc_type)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def new_change_id(paths: Paths, date: str, service_id: str, doc_type: str) -> str:
    base = f"{date}-{service_id}-{doc_type}"
    cid, n = base, 2
    while (paths.changes / f"{cid}.json").exists():
        cid = f"{base}-{n}"
        n += 1
    return cid


def save_change(paths: Paths, change: dict) -> None:
    paths.changes.mkdir(parents=True, exist_ok=True)
    (paths.changes / f"{change['id']}.json").write_text(
        json.dumps(change, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_changes(paths: Paths) -> list[dict]:
    if not paths.changes.exists():
        return []
    changes = [json.loads(p.read_text(encoding="utf-8")) for p in paths.changes.glob("*.json")]
    return sorted(changes, key=lambda c: (c["detected_at"], c["id"]), reverse=True)


def load_status(paths: Paths) -> dict:
    if paths.status.exists():
        return json.loads(paths.status.read_text(encoding="utf-8"))
    return {}


def save_status(paths: Paths, status: dict) -> None:
    paths.status.parent.mkdir(parents=True, exist_ok=True)
    paths.status.write_text(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
