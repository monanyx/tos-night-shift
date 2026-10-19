"""Gets the raw HTML of a policy page — plain HTTP, or a headless browser for JS-heavy sites."""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import __version__

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/129.0 Safari/537.36 ToSNightShift/{__version__}"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchError(Exception):
    pass


def decode(resp: requests.Response) -> str:
    """Pages without a declared charset get mis-read as Latin-1 by requests (â instead of ’). Prefer UTF-8."""
    declared = "charset=" in resp.headers.get("Content-Type", "").lower()
    if declared and resp.encoding and resp.encoding.lower() not in ("iso-8859-1", "latin-1"):
        return resp.text
    try:
        return resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return resp.content.decode(resp.apparent_encoding or "cp1252", errors="replace")


def fetch(url: str, render: bool = False, timeout: int = 30, retries: int = 2) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        # Used by tests and local experiments.
        return Path(parsed.path).read_text(encoding="utf-8")
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"unsupported URL scheme: {url}")
    if render:
        return _fetch_rendered(url, timeout)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code}")
            return decode(resp)
        except (requests.RequestException, FetchError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise FetchError(str(last_error))


def _fetch_rendered(url: str, timeout: int) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise FetchError("render: true needs Playwright (pip install playwright && playwright install chromium)") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=USER_AGENT, locale="en-US")
            page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            page.wait_for_timeout(1500)
            return page.content()
        except Exception as exc:  # playwright raises its own error types
            raise FetchError(f"render failed: {exc}") from exc
        finally:
            browser.close()
