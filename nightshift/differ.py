"""Compares two versions of a policy and produces the receipts."""

from __future__ import annotations

import difflib
import html
import re
from dataclasses import asdict, dataclass

DATE_LINE = re.compile(
    r"(last\s+(updated|modified|revised)|effective(\s+date)?|updated\s+on|version\s+date)",
    re.IGNORECASE,
)
WORD = re.compile(r"\s*\S+\s*")  # words carry their spacing, so changed runs highlight as one phrase


@dataclass
class Hunk:
    kind: str          # "added" | "removed" | "changed"
    old: list[str]
    new: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def paragraphs(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def diff(old_text: str, new_text: str) -> list[Hunk]:
    a, b = paragraphs(old_text), paragraphs(new_text)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    hunks: list[Hunk] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            hunks.append(Hunk("added", [], b[j1:j2]))
        elif tag == "delete":
            hunks.append(Hunk("removed", a[i1:i2], []))
        else:
            hunks.append(Hunk("changed", a[i1:i2], b[j1:j2]))
    return hunks


def is_date_only(hunks: list[Hunk]) -> bool:
    """True when the only thing that moved is a 'Last updated' style line."""
    if not hunks:
        return False
    for h in hunks:
        for line in h.old + h.new:
            if len(line) > 160 or not DATE_LINE.search(line):
                return False
    return True


def looks_broken(old_text: str, new_text: str) -> str | None:
    """Catch blocked pages, captchas and empty renders before they become fake 'they deleted everything' news."""
    old_len, new_len = len(old_text), len(new_text)
    if new_len < 400:
        return f"extracted text is only {new_len} characters"
    if old_len and new_len < 0.35 * old_len:
        return f"text shrank from {old_len} to {new_len} characters — probably a blocked or broken page"
    lowered = new_text.lower()
    for marker in ("captcha", "access denied", "are you a robot", "enable javascript", "request blocked"):
        if marker in lowered and new_len < 3000:
            return f"page looks like a block screen ('{marker}')"
    return None


def stats(hunks: list[Hunk]) -> dict:
    added = sum(len(" ".join(h.new).split()) for h in hunks)
    removed = sum(len(" ".join(h.old).split()) for h in hunks)
    return {"hunks": len(hunks), "added_words": added, "removed_words": removed}


def unified_for_prompt(hunks: list[Hunk], limit: int = 14000) -> tuple[str, bool]:
    out: list[str] = []
    for n, h in enumerate(hunks, 1):
        out.append(f"@@ change {n} ({h.kind}) @@")
        out += [f"- {line}" for line in h.old]
        out += [f"+ {line}" for line in h.new]
    text = "\n".join(out)
    if len(text) > limit:
        return text[:limit] + "\n[... diff truncated ...]", True
    return text, False


def word_diff_html(old: str, new: str) -> tuple[str, str]:
    """Word-level highlighting for a changed paragraph pair. Returns (old_html, new_html)."""
    a, b = WORD.findall(old), WORD.findall(new)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    old_out, new_out = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a_chunk = html.escape("".join(a[i1:i2]))
        b_chunk = html.escape("".join(b[j1:j2]))
        if tag == "equal":
            old_out.append(a_chunk)
            new_out.append(b_chunk)
        else:
            if a_chunk:
                core = a_chunk.rstrip()
                old_out.append(f"<del>{core}</del>{a_chunk[len(core):]}")
            if b_chunk:
                core = b_chunk.rstrip()
                new_out.append(f"<ins>{core}</ins>{b_chunk[len(core):]}")
    return "".join(old_out), "".join(new_out)
