"""Explains a policy change in plain words. Claude if there's an API key, the keyword radar if not."""

from __future__ import annotations

import json
import os
import re

from . import flags as radar
from .differ import Hunk, stats, unified_for_prompt

DEFAULT_MODEL = "claude-sonnet-5-5"
ALLOWED_TAGS = sorted(radar.RADAR) + ["cosmetic", "other"]

SYSTEM_PROMPT = f"""You are the writer for ToS Night Shift, a public watchdog that catches companies quietly changing their Terms of Service and Privacy Policies.

You get a diff between yesterday's and today's version of one policy. Lines starting with "-" were removed, "+" were added.

Your job: tell a normal person what actually changed and whether they should care.

Hard rules — credibility is the whole product:
1. Only describe what the diff shows. Never guess at motives, never invent facts, never mention things that are not in the diff.
2. If the change is cosmetic (typos, formatting, renumbering, links, dates), say so plainly and give side-eye 0 or 1.
3. "receipt" must be copied word for word from a "+" line (or a "-" line if the important thing is what they removed). Max 40 words.
4. Plain language, short sentences. A little attitude is good; exaggeration is not. No legal advice.
5. Side-eye scale: 0 = nothing, 1 = housekeeping, 2 = worth knowing, 3 = you would want to be told, 4 = most people would object, 5 = screenshot this.

Reply with ONLY a JSON object, no code fence:
{{"headline": "<max 90 chars, names the company, says what changed>",
  "summary": "<2-4 sentences: what changed, what it means for the user>",
  "receipt": "<exact quote from the diff>",
  "receipt_side": "new" | "old",
  "sideeye": <integer 0-5>,
  "tags": [<zero or more of: {", ".join(ALLOWED_TAGS)}>]}}"""


def summarize(service_name: str, doc_label: str, url: str, hunks: list[Hunk], date_only: bool = False,
              use_ai: bool = True) -> dict:
    found = radar.scan(hunks)
    base = {"flags": found, "stats": stats(hunks)}

    if date_only:
        return {
            **base,
            "headline": f"{service_name} bumped the date on its {doc_label}",
            "summary": "Only the 'last updated' line changed in the text we can see. Either it's housekeeping, "
                       "or the change is somewhere we can't read. Keeping an eye on it.",
            "receipt": next((line for h in hunks for line in h.new), ""),
            "receipt_side": "new",
            "sideeye": 1,
            "tags": ["cosmetic"],
            "summary_source": "date-only",
        }

    if use_ai and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            ai = _summarize_with_claude(service_name, doc_label, url, hunks, found)
            return {**base, **ai, "summary_source": "ai"}
        except Exception as exc:  # never let a flaky API kill the night shift
            print(f"  ! AI summary failed, using keyword radar instead: {exc}")

    return {**base, **_summarize_with_radar(service_name, doc_label, hunks, found), "summary_source": "radar"}


def _summarize_with_claude(service_name: str, doc_label: str, url: str, hunks: list[Hunk], found: list[dict]) -> dict:
    import anthropic

    diff_text, truncated = unified_for_prompt(hunks)
    radar_hint = ", ".join(f["label"] for f in found) or "nothing"
    user = (
        f"Company: {service_name}\nDocument: {doc_label}\nURL: {url}\n"
        f"Keyword radar noticed new mentions of: {radar_hint} (hints only — verify against the diff)\n"
        f"{'NOTE: the diff was truncated, it is a big rewrite.' if truncated else ''}\n\n"
        f"DIFF:\n{diff_text}"
    )
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    msg = client.messages.create(
        model=os.environ.get("NIGHTSHIFT_MODEL") or DEFAULT_MODEL,
        max_tokens=900,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
    data = _parse_json(text)
    return _validate(data, hunks)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start : end + 1])


def _validate(data: dict, hunks: list[Hunk]) -> dict:
    headline = str(data.get("headline", "")).strip()[:120]
    summary = str(data.get("summary", "")).strip()
    receipt = str(data.get("receipt", "")).strip()
    side = data.get("receipt_side") if data.get("receipt_side") in ("new", "old") else "new"
    try:
        score = max(0, min(5, int(data.get("sideeye", 0))))
    except (TypeError, ValueError):
        score = 0
    tags = [t for t in data.get("tags", []) if t in ALLOWED_TAGS]
    if not headline or not summary:
        raise ValueError("model reply missing headline or summary")

    # Receipts or it didn't happen: the quote must really be in the diff.
    haystack = _squash(" ".join(line for h in hunks for line in h.old + h.new))
    if receipt and _squash(receipt).rstrip(" .…") not in haystack:
        print("  ! model receipt not found verbatim in diff — swapping in a real one")
        receipt = radar.best_receipt(hunks, tags)
        side = "new"
    return {"headline": headline, "summary": summary, "receipt": receipt,
            "receipt_side": side, "sideeye": score, "tags": tags}


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _summarize_with_radar(service_name: str, doc_label: str, hunks: list[Hunk], found: list[dict]) -> dict:
    st = stats(hunks)
    tags = [f["tag"] for f in found]
    labels = [f["label"] for f in found]
    big = st["added_words"] + st["removed_words"] > 400
    score = min(5, len(tags) + (1 if big else 0) + (1 if {"ai-training", "arbitration", "content-license", "biometrics"} & set(tags) else 0))
    if tags:
        ph = [radar.PHRASES.get(t, t) for t in tags]
        topic = ph[0] if len(ph) == 1 else (f"{ph[0]} and {ph[1]}" if len(ph) == 2 else f"{ph[0]}, {ph[1]} and more")
        headline = f"{service_name} rewrote its {doc_label} — new wording on {topic}"
    else:
        headline = f"{service_name} edited its {doc_label}"
    summary = (
        f"{st['added_words']} words added and {st['removed_words']} removed across {st['hunks']} section"
        f"{'s' if st['hunks'] != 1 else ''}. "
        + (f"New wording touches: {', '.join(labels)}. " if labels else "No red-flag keywords in the new text. ")
        + "Read the receipts below — this summary is automatic, not AI."
    )
    return {"headline": headline[:120], "summary": summary, "receipt": radar.best_receipt(hunks, tags),
            "receipt_side": "new", "sideeye": score, "tags": tags or ["other"]}
