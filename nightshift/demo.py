"""Builds a demo site from three fictional apps, so anyone can see what the night shift catches."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import Paths
from .runner import run
from .site import build

FIX = Path(__file__).parent / "demo_fixtures"

# (id, name, doc type, fixture prefix, days ago the change was "caught")
APPS = [
    ("glimmer", "Glimmer", "terms", "glimmer", 0),
    ("loop", "Loop", "privacy", "loop", 4),
    ("snackr", "Snackr", "terms", "snackr", 9),
]


def build_demo(out_root: Path) -> Path:
    from datetime import datetime, timedelta, timezone

    out_root.mkdir(parents=True, exist_ok=True)
    live = out_root / "live"
    live.mkdir(exist_ok=True)
    lines = ["site:", "  title: ToS Night Shift", "  demo: true", "services:"]
    for sid, name, dtype, prefix, _ in APPS:
        shutil.copy(FIX / f"{prefix}_v1.html", live / f"{sid}.html")
        lines += [f"  - id: {sid}", f"    name: {name}", "    documents:",
                  f"      - type: {dtype}", f"        url: file://{live / (sid + '.html')}"]
    services = out_root / "services.yaml"
    services.write_text("\n".join(lines) + "\n", encoding="utf-8")

    run(out_root, services)                      # night 1: baseline
    for sid, _, _, prefix, _ in APPS:
        shutil.copy(FIX / f"{prefix}_v2.html", live / f"{sid}.html")
    run(out_root, services)                      # night 2: catch the changes

    # Make the demo look like a few nights of history, with placeholder policy links.
    paths = Paths(out_root)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    days = {sid: d for sid, _, _, _, d in APPS}
    for f in paths.changes.glob("*.json"):
        c = json.loads(f.read_text(encoding="utf-8"))
        when = now - timedelta(days=days[c["service"]], hours=3)
        c["detected_at"] = when.isoformat()
        c["url"] = f"https://example.com/{c['service']}/{c['doc']}"
        c["id"] = f"{when.date()}-{c['service']}-{c['doc']}"
        f.unlink()
        (paths.changes / f"{c['id']}.json").write_text(json.dumps(c, indent=2), encoding="utf-8")
    status = json.loads(paths.status.read_text(encoding="utf-8"))
    for key, st in status.items():
        st["url"] = f"https://example.com/{key}"
        st["last_changed"] = (now - timedelta(days=days[st["service_id"]], hours=3)).isoformat()
    paths.status.write_text(json.dumps(status, indent=2), encoding="utf-8")

    return build(out_root, services)
