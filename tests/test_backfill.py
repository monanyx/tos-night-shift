"""Backfill tests with a fake Internet Archive — no network needed."""

import json
from pathlib import Path

import pytest

from nightshift.backfill import backfill, thin, ts_to_iso

FIX = Path(__file__).parent / "fixtures"
PAGES = {
    "20240110120000": "glimmer_v1.html",
    "20240210120000": "glimmer_v1.html",   # archive saved it again, nothing changed
    "20240501080000": "glimmer_v2.html",   # the sneaky update
    "20240601080000": "blocked.html",      # archive saved a captcha page
    "20240701080000": "glimmer_v2.html",
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    services = tmp_path / "services.yaml"
    services.write_text(
        "services:\n  - id: glimmer\n    name: Glimmer\n    documents:\n"
        "      - type: terms\n        url: https://glimmer.example/terms\n",
        encoding="utf-8",
    )
    return tmp_path, services


def fake_list(url, since="2023"):
    return [{"timestamp": ts, "original": url, "digest": ts} for ts in sorted(PAGES)]


def fake_html(ts, url, render=False):
    return (FIX / PAGES[ts]).read_text()


def run(root, services, **kw):
    return backfill(root, services, list_fn=fake_list, html_fn=fake_html, sleep=lambda s: None, **kw)


def test_replays_history_and_dates_the_change(repo):
    root, services = repo
    total = run(root, services, max_captures=0)
    assert total["changes"] == 1

    [path] = (root / "data" / "changes").glob("*.json")
    c = json.loads(path.read_text())
    assert c["source"] == "wayback"
    assert c["detected_at"] == ts_to_iso("20240501080000")
    assert c["window_start"] == ts_to_iso("20240210120000")   # last copy that still had the old text
    assert c["archive_before"].startswith("https://web.archive.org/web/20240210120000/")
    assert c["archive_after"].startswith("https://web.archive.org/web/20240501080000/")
    assert {"ai-training", "arbitration"} <= {f["tag"] for f in c["flags"]}

    # nightly run gets a starting point from the newest archived copy
    assert "irrevocable" in (root / "snapshots/glimmer/terms.md").read_text()


def test_resumes_instead_of_redoing(repo):
    root, services = repo
    run(root, services, max_captures=0)
    again = run(root, services, max_captures=0)
    assert again["skipped"] == 1 and again["changes"] == 0


def test_site_shows_archive_proof(repo):
    from nightshift.site import build
    root, services = repo
    run(root, services, max_captures=0)
    out = build(root, services)
    page = next((out / "c").glob("*.html")).read_text()
    assert "Archived before" in page and "found in the Internet Archive" in page
    assert "from the archive" in (out / "index.html").read_text()


def test_thin_keeps_first_last_and_spacing():
    caps = [{"timestamp": f"2024{m:02d}{d:02d}000000"} for m in range(1, 13) for d in (1, 3, 15)]
    out = thin(caps, max_n=10)
    assert len(out) == 10
    assert out[0] is caps[0] and out[-1] is caps[-1]
    weekly = thin(caps, max_n=0)
    assert len(weekly) < len(caps)  # 1st and 3rd of the month are too close together
