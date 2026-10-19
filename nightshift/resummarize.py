"""Re-write keyword-radar summaries with AI — e.g. after adding or fixing the API key. No refetching."""

from __future__ import annotations

import os
from pathlib import Path

from . import store
from .config import Paths
from .differ import Hunk, is_date_only
from .summarize import summarize


def resummarize(root: Path, only: str | None = None, limit: int = 100) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY set — nothing to do.")
        return 0
    paths = Paths(root)
    done = 0
    for c in store.load_changes(paths):
        if done >= limit:
            print(f"Stopped after {limit} summaries. Run again for the rest.")
            break
        if c.get("summary_source") != "radar" or (only and c["service"] != only):
            continue
        hunks = [Hunk(**h) for h in c.get("hunks", [])]
        s = summarize(c["service_name"], c["doc_label"], c["url"], hunks, date_only=is_date_only(hunks))
        if s.get("summary_source") != "ai":
            print(f"  ✗ {c['id']}: AI still failing, stopping here")
            break
        c.update(s)
        store.save_change(paths, c)
        done += 1
        print(f"  ✓ {c['id']} — {c['sideeye']}/5 — {c['headline']}", flush=True)
    print(f"{done} summaries rewritten by AI")
    return done
