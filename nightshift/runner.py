"""The night shift itself: check every policy, catch what changed, write it all down."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .config import Paths, load_services
from .differ import diff, is_date_only, looks_broken
from .extract import extract_text
from .fetch import FetchError, fetch
from .summarize import summarize


def run(root: Path, services_file: Path, only: str | None = None) -> dict:
    paths = Paths(root)
    services = load_services(services_file)
    status = store.load_status(paths)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    today = now[:10]
    tally = {"checked": 0, "baseline": 0, "unchanged": 0, "changed": 0, "suspicious": 0, "error": 0}
    caught: list[dict] = []

    for svc in services:
        if only and svc.id != only:
            continue
        for doc in svc.documents:
            key = f"{svc.id}/{doc.type}"
            st = status.get(key, {})
            st.update(service=svc.name, service_id=svc.id, doc=doc.label, doc_type=doc.type,
                      url=doc.url, last_checked=now)
            status[key] = st
            tally["checked"] += 1
            print(f"· {svc.name} — {doc.label}")

            try:
                html = fetch(doc.url, render=doc.render)
                text = extract_text(html, selector=doc.selector, url=doc.url)
            except (FetchError, ValueError, OSError) as exc:
                st.update(status="error", error=str(exc), fail_count=st.get("fail_count", 0) + 1)
                tally["error"] += 1
                print(f"  ✗ {exc}")
                continue

            old = store.read_snapshot(paths, svc.id, doc.type)
            if old is None:
                problem = looks_broken("", text)
                if problem:
                    st.update(status="suspicious", error=problem)
                    tally["suspicious"] += 1
                    print(f"  ? not saving first copy: {problem}")
                    continue
                store.write_snapshot(paths, svc.id, doc.type, text)
                st.update(status="baseline", error=None, fail_count=0, chars=len(text), since=now)
                tally["baseline"] += 1
                print(f"  ✓ first copy saved ({len(text):,} chars)")
                continue

            problem = looks_broken(old, text)
            if problem:
                # Keep yesterday's snapshot. A blocked page is not a policy change.
                st.update(status="suspicious", error=problem)
                tally["suspicious"] += 1
                print(f"  ? skipped: {problem}")
                continue

            hunks = diff(old, text)
            if not hunks:
                st.update(status="ok", error=None, fail_count=0, chars=len(text))
                tally["unchanged"] += 1
                continue

            summary = summarize(svc.name, doc.label, doc.url, hunks, date_only=is_date_only(hunks))
            change = {
                "id": store.new_change_id(paths, today, svc.id, doc.type),
                "service": svc.id,
                "service_name": svc.name,
                "doc": doc.type,
                "doc_label": doc.label,
                "url": doc.url,
                "detected_at": now,
                **summary,
                "hunks": [h.to_dict() for h in hunks],
            }
            store.save_change(paths, change)
            store.write_snapshot(paths, svc.id, doc.type, text)
            st.update(status="changed", error=None, fail_count=0, chars=len(text),
                      last_change=change["id"], last_changed=now)
            tally["changed"] += 1
            caught.append(change)
            print(f"  👀 CHANGED — side-eye {change['sideeye']}/5 — {change['headline']}")

    store.save_status(paths, status)
    _write_job_summary(tally, caught)
    print("\n" + "  ".join(f"{k}: {v}" for k, v in tally.items()))
    return {"tally": tally, "caught": caught}


def _write_job_summary(tally: dict, caught: list[dict]) -> None:
    """Pretty summary on the GitHub Actions run page."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    lines = ["## 🌙 Night shift report", "", " · ".join(f"**{k}** {v}" for k, v in tally.items()), ""]
    for c in caught:
        lines.append(f"- **{c['sideeye']}/5** {c['headline']}")
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
