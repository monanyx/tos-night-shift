"""End-to-end test with a fictional app — no network, no API key needed."""

import json
import shutil
from pathlib import Path

import pytest

from nightshift.differ import diff, is_date_only, looks_broken
from nightshift.runner import run
from nightshift.site import build

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    live = tmp_path / "live.html"
    shutil.copy(FIXTURES / "glimmer_v1.html", live)
    services = tmp_path / "services.yaml"
    services.write_text(
        "site:\n  title: ToS Night Shift\n  repo: https://github.com/example/tos-night-shift\n"
        "services:\n"
        "  - id: glimmer\n    name: Glimmer\n    documents:\n"
        f"      - type: terms\n        url: file://{live}\n",
        encoding="utf-8",
    )
    return tmp_path, services, live


def test_first_night_saves_baseline_only(repo):
    root, services, _ = repo
    result = run(root, services)
    assert result["tally"]["baseline"] == 1
    assert result["caught"] == []
    snap = (root / "snapshots/glimmer/terms.md").read_text()
    assert "You own the photos" in snap
    assert "Accept all" not in snap and "window.tracking" not in snap


def test_catches_sneaky_change_with_receipts(repo):
    root, services, live = repo
    run(root, services)
    shutil.copy(FIXTURES / "glimmer_v2.html", live)
    result = run(root, services)

    assert result["tally"]["changed"] == 1
    c = result["caught"][0]
    flagged = {f["tag"] for f in c["flags"]}
    assert {"ai-training", "arbitration", "content-license", "data-sharing"} <= flagged
    assert c["sideeye"] >= 4
    assert c["summary_source"] == "radar"
    assert c["receipt"] and c["receipt"].split()[0] in json.dumps(c["hunks"])

    out = build(root, services)
    index = (out / "index.html").read_text()
    page = (out / "c" / f"{c['id']}.html").read_text()
    assert c["headline"] in index.replace("&#39;", "'").replace("&amp;", "&")
    assert "<ins>" in page and "<del>" in page
    assert (out / "feed.xml").exists() and (out / "api/changes.json").exists()


def test_nothing_new_means_no_noise(repo):
    root, services, _ = repo
    run(root, services)
    result = run(root, services)
    assert result["tally"]["unchanged"] == 1 and result["caught"] == []


def test_blocked_page_is_not_news(repo):
    root, services, live = repo
    run(root, services)
    before = (root / "snapshots/glimmer/terms.md").read_text()
    shutil.copy(FIXTURES / "blocked.html", live)
    result = run(root, services)
    assert result["tally"]["suspicious"] == 1 and result["caught"] == []
    assert (root / "snapshots/glimmer/terms.md").read_text() == before


def test_date_only_change_detection():
    old = "Last updated: March 3, 2026\nSome long policy text that stays the same.\n"
    new = "Last updated: October 1, 2026\nSome long policy text that stays the same.\n"
    assert is_date_only(diff(old, new))
    assert not is_date_only(diff(old, new + "We now sell your data.\n"))


def test_shrinking_page_is_suspicious():
    assert looks_broken("x" * 5000, "y" * 500)
    assert looks_broken("x" * 5000, "z" * 4800) is None


def test_ai_receipt_must_be_real():
    from nightshift.differ import Hunk
    from nightshift.summarize import _validate
    hunks = [Hunk("added", [], ["We may use your photos to train our AI models."])]
    good = _validate({"headline": "X trains AI on photos", "summary": "They do.", "receipt": "use your photos to train our AI models",
                      "sideeye": 9, "tags": ["ai-training", "made-up"]}, hunks)
    assert good["sideeye"] == 5 and good["tags"] == ["ai-training"]
    faked = _validate({"headline": "X sells kidneys", "summary": "Lies.", "receipt": "we harvest kidneys", "sideeye": 5, "tags": []}, hunks)
    assert faked["receipt"] == "We may use your photos to train our AI models."


def test_utf8_page_without_charset_is_not_mangled():
    import requests
    from nightshift.fetch import decode
    r = requests.models.Response()
    r._content = "Discord’s “content” rules".encode("utf-8")
    r.headers["Content-Type"] = "text/html"
    r.encoding = "ISO-8859-1"
    assert decode(r) == "Discord’s “content” rules"


def test_stats_count_real_edits_only():
    from nightshift.differ import Hunk, stats
    old = "We collect your name and email address to run the service for you every day."
    new = "We collect your name, email address and location to run the service for you every day."
    s = stats([Hunk("changed", [old], [new])])
    assert s["added_words"] <= 4 and s["removed_words"] <= 2
