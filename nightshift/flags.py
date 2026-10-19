"""Keyword radar. Runs on every change, with or without AI, so the side-eye never depends on an API key."""

from __future__ import annotations

import re

from .differ import Hunk

# tag -> (label, patterns)
RADAR: dict[str, tuple[str, list[str]]] = {
    "ai-training": ("AI training", [
        r"\bartificial intelligence\b", r"\bmachine learning\b", r"\b(train|training|trained)\b.{0,40}\b(model|AI|algorithm)s?\b",
        r"\bgenerative\b", r"\blarge language model", r"\bAI (features|models|systems|services)\b",
    ]),
    "data-sharing": ("Data sharing", [
        r"\bsell\b.{0,30}\b(data|information)\b", r"\bshare\b.{0,40}\b(partners|affiliates|third[- ]part(y|ies)|advertisers)\b",
        r"\bdata brokers?\b", r"\bdisclose\b.{0,30}\bthird[- ]part",
    ]),
    "arbitration": ("Arbitration / no lawsuits", [
        r"\barbitration\b", r"\bclass[- ]action\b", r"\bwaive\b.{0,30}\b(right|jury)\b", r"\bjury trial\b",
    ]),
    "content-license": ("Rights to your content", [
        r"\b(perpetual|irrevocable|royalty[- ]free|sublicensable|worldwide)\b.{0,60}\blicen[cs]e\b",
        r"\blicen[cs]e\b.{0,60}\b(perpetual|irrevocable|royalty[- ]free|sublicensable)\b",
    ]),
    "tracking": ("Tracking", [
        r"\b(cookies?|pixels?|web beacons?|device identifiers?|fingerprint(ing)?)\b", r"\bcross[- ](site|device|app)\b",
        r"\btargeted advertising\b", r"\bpersonali[sz]ed (ads|advertising)\b",
    ]),
    "location": ("Location", [r"\b(precise|approximate|gps|geo)?\s*location (data|information)\b", r"\bgeolocation\b"]),
    "biometrics": ("Biometrics", [r"\bbiometric", r"\bface(print| geometry| recognition)\b", r"\bvoice ?print\b"]),
    "minors": ("Kids & teens", [r"\b(minors?|children|teens?|under (13|16|18))\b"]),
    "retention": ("How long they keep it", [r"\bretain\b", r"\bretention\b", r"\bstore\b.{0,30}\b(indefinitely|as long as)\b"]),
    "account-termination": ("Kicking you out", [r"\b(suspend|terminate|disable)\b.{0,40}\baccount", r"\bat (our|its) sole discretion\b"]),
    "payments": ("Money", [r"\b(fees?|subscription|auto[- ]?renew(al)?|refunds?|price changes?)\b"]),
}

# How each tag reads mid-sentence in an automatic headline.
PHRASES = {
    "ai-training": "AI training", "data-sharing": "sharing your data", "arbitration": "your right to sue",
    "content-license": "rights to your content", "tracking": "tracking", "location": "your location",
    "biometrics": "biometrics", "minors": "kids and teens", "retention": "how long they keep your data",
    "account-termination": "banning accounts", "payments": "fees and billing",
}

COMPILED = {tag: (label, [re.compile(p, re.IGNORECASE) for p in pats]) for tag, (label, pats) in RADAR.items()}
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def scan(hunks: list[Hunk]) -> list[dict]:
    """Which radar tags show up in text that is NEW in this version."""
    added_text = "\n".join(line for h in hunks for line in h.new)
    removed_text = "\n".join(line for h in hunks for line in h.old)
    found = []
    for tag, (label, pats) in COMPILED.items():
        # Flag phrases that are genuinely new — not ones that were already there and just got moved around.
        new_phrases = {m.group(0).lower() for p in pats for m in p.finditer(added_text)}
        old_phrases = {m.group(0).lower() for p in pats for m in p.finditer(removed_text)}
        fresh = new_phrases - old_phrases
        if fresh:
            found.append({"tag": tag, "label": label, "hits": len(fresh)})
    return sorted(found, key=lambda f: -f["hits"])


def best_receipt(hunks: list[Hunk], tags: list[str]) -> str:
    """The single most damning sentence from the new text."""
    pats = [p for t in tags for p in COMPILED.get(t, ("", []))[1]]
    candidates = [s.strip() for h in hunks for line in h.new for s in SENTENCE.split(line) if s.strip()]
    for s in candidates:
        if any(p.search(s) for p in pats):
            return _trim(s)
    return _trim(candidates[0]) if candidates else ""


def _trim(s: str, words: int = 40) -> str:
    parts = s.split()
    return s if len(parts) <= words else " ".join(parts[:words]) + " …"
