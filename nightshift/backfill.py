"""
Wayback backfill: replay old copies of every policy from the Internet Archive,
so the site launches with years of real history instead of an empty page.

Every change found this way is dated to when it actually happened and links to
both archived copies (before and after) as proof.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from . import store
from .config import Paths, load_services
from .differ import diff, is_date_only, looks_broken, stats
from .extract import extract_text
from .fetch import HEADERS, FetchError, fetch
from .summarize import summarize

CDX_API = "https://web.archive.org/cdx/search/cdx"
MIN_WORDS = 3  # smaller wiggles between archive copies are page noise, not policy changes


def archive_link(ts: str, url: str) -> str:
    """A human-viewable archived copy, with the Wayback toolbar."""
    return f"https://web.archive.org/web/{ts}/{url}"


def ts_to_iso(ts: str) -> str:
    return datetime.strptime(ts[:14].ljust(14, "0"), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()


def _get(url: str, params: dict | None = None, tries: int = 4, timeout: int = 60) -> requests.Response:
    """The archive is slow and rate-limits hard, so back off generously."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if resp.status_code in (429, 502, 503, 504):
                raise FetchError(f"HTTP {resp.status_code}")
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}")
            return resp
        except (requests.RequestException, FetchError) as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(10 * (attempt + 1) ** 2)  # 10s, 40s, 90s
    raise FetchError(f"archive unreachable: {last}")


def list_captures(url: str, since: str = "2022", until: str | None = None) -> list[dict]:
    """Every distinct saved copy of a page (identical copies already collapsed by the archive)."""
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original,digest",
        "filter": "statuscode:200",
        "collapse": "digest",
        "from": since,
    }
    if until:
        params["to"] = until
    rows = _get(CDX_API, params).json() or []
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    caps = [dict(zip(header, r)) for r in body]
    return sorted(caps, key=lambda c: c["timestamp"])


def archived_html(ts: str, url: str, render: bool = False) -> str:
    if render:
        # if_ = archived page without the Wayback toolbar, with links rewritten so scripts still load
        return fetch(f"https://web.archive.org/web/{ts}if_/{url}", render=True, timeout=90)
    # id_ = the original HTML exactly as the site served it
    return _get(f"https://web.archive.org/web/{ts}id_/{url}").text


def thin(captures: list[dict], max_n: int, min_gap_days: int = 7) -> list[dict]:
    """Keep at most one copy a week and at most max_n overall, always keeping the first and last."""
    if not captures:
        return []
    kept = [captures[0]]
    for cap in captures[1:]:
        gap = (datetime.strptime(cap["timestamp"][:8], "%Y%m%d") -
               datetime.strptime(kept[-1]["timestamp"][:8], "%Y%m%d")).days
        if gap >= min_gap_days:
            kept.append(cap)
    if kept[-1] is not captures[-1]:
        kept.append(captures[-1])
    if max_n and len(kept) > max(max_n, 2):
        max_n = max(max_n, 2)
        step = (len(kept) - 1) / (max_n - 1)
        kept = [kept[round(i * step)] for i in range(max_n)]
    return kept


def _progress_path(paths: Paths) -> Path:
    return paths.root / "data" / "backfill.json"


def backfill(
    root: Path,
    services_file: Path,
    only: str | None = None,
    since: str = "2023",
    max_captures: int = 30,
    max_ai: int = 40,
    pause: float = 4.0,
    redo: bool = False,
    time_budget_min: float = 0,
    list_fn: Callable[..., list[dict]] = list_captures,
    html_fn: Callable[..., str] = archived_html,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    paths = Paths(root)
    services = load_services(services_file)
    prog_file = _progress_path(paths)
    progress = json.loads(prog_file.read_text(encoding="utf-8")) if prog_file.exists() else {}
    started = time.monotonic()
    ai_used = 0
    total = {"documents": 0, "captures": 0, "changes": 0, "skipped": 0}

    for svc in services:
        if only and svc.id != only:
            continue
        for doc in svc.documents:
            key = f"{svc.id}/{doc.type}"
            if progress.get(key, {}).get("done") and not redo:
                total["skipped"] += 1
                continue
            if time_budget_min and (time.monotonic() - started) / 60 > time_budget_min:
                print("⏸ time budget used up — run backfill again to continue where it stopped")
                _save(prog_file, progress)
                return total

            src_url = doc.archive_url or doc.url
            print(f"· {svc.name} — {doc.label}")
            try:
                caps = thin(list_fn(src_url, since=since), max_captures)
            except FetchError as exc:
                print(f"  ✗ could not list archive copies: {exc}")
                progress[key] = {"done": False, "error": str(exc)}
                _save(prog_file, progress)
                continue
            print(f"  {len(caps)} archived copies to replay", flush=True)

            prev_text = prev_ts = None
            found = 0
            for cap in caps:
                ts = cap["timestamp"]
                try:
                    html = html_fn(ts, cap.get("original", src_url), render=doc.render)
                    text = extract_text(html, selector=doc.selector, url=doc.url)
                except (FetchError, ValueError, OSError) as exc:
                    print(f"  ✗ {ts}: {exc}")
                    sleep(pause)
                    continue
                sleep(pause)
                total["captures"] += 1
                print(f"  · {ts[:8]} ok ({len(text):,} chars)", flush=True)

                if prev_text is None:
                    if not looks_broken("", text):
                        prev_text, prev_ts = text, ts
                    continue
                if looks_broken(prev_text, text):
                    continue

                hunks = diff(prev_text, text)
                if not hunks:
                    prev_ts = ts  # old text still live at this point, so the change came later
                    continue
                st = stats(hunks)
                if st["added_words"] + st["removed_words"] < MIN_WORDS:
                    prev_text, prev_ts = text, ts
                    continue

                use_ai = ai_used < max_ai
                summary = summarize(svc.name, doc.label, doc.url, hunks,
                                    date_only=is_date_only(hunks), use_ai=use_ai)
                if summary.get("summary_source") == "ai":
                    ai_used += 1
                when = ts_to_iso(ts)
                change = {
                    "id": store.new_change_id(paths, when[:10], svc.id, doc.type),
                    "service": svc.id,
                    "service_name": svc.name,
                    "doc": doc.type,
                    "doc_label": doc.label,
                    "url": doc.url,
                    "detected_at": when,
                    "source": "wayback",
                    "window_start": ts_to_iso(prev_ts),
                    "archive_before": archive_link(prev_ts, cap.get("original", src_url)),
                    "archive_after": archive_link(ts, cap.get("original", src_url)),
                    **summary,
                    "hunks": [h.to_dict() for h in hunks],
                }
                store.save_change(paths, change)
                found += 1
                total["changes"] += 1
                print(f"  👀 {when[:10]} — side-eye {change['sideeye']}/5 — {change['headline']}")
                prev_text, prev_ts = text, ts

            # Give the nightly run a starting point if it has none, so the gap
            # between the last archived copy and today gets caught too.
            if prev_text and not doc.render and store.read_snapshot(paths, svc.id, doc.type) is None:
                store.write_snapshot(paths, svc.id, doc.type, prev_text)

            progress[key] = {"done": True, "copies": len(caps), "changes": found,
                             "last_copy": ts_to_iso(prev_ts) if prev_ts else None}
            _save(prog_file, progress)
            total["documents"] += 1

    print("\n" + "  ".join(f"{k}: {v}" for k, v in total.items()) + f"  ai summaries: {ai_used}")
    return total


def _save(path: Path, progress: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")
