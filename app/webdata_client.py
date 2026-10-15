"""Fetch pages through a managed Web Data API (Decodo Web Scraping API).

The caller hands over a target URL and gets the page's raw HTML back; the API
handles proxies and retries. Standard library only.

Settings come from environment variables, or from a local .env file in the
project root (git-ignored; see .env.example):

    WEBDATA_API_KEY     Decodo Web Data API key (current plans), or the older
                        "Basic authentication token" (base64 user:password)
    WEBDATA_API_URL     optional; overrides the endpoint picked from the key type
    WEBDATA_JS_RENDER   optional; "1" asks the API to render JavaScript

Safety behaviour:
  - a URL that the site's robots.txt disallows is refused before any request
  - a block/challenge page, or a 403/429/503 from the site, raises
    AccessBlockedError so the caller stops instead of retrying
"""
import base64
import binascii
import json
import os
import re
import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
# Endpoints and auth per key type, as in Decodo's official SDK (github.com/Decodo/sdk-go).
API_KEY_URL = "https://data.decodo.com/v1/scrape"           # Authorization: Bearer <api key>
BASIC_TOKEN_URL = "https://scraper-api.decodo.com/v2/scrape"  # Authorization: Basic <token>
API_TIMEOUT_SECONDS = 180  # the API retries internally before it answers
# Dropped connections and temporary API errors are retried after these pauses.
# A bad key or an exhausted plan (401/402/403) is not retried.
RETRY_DELAYS_SECONDS = (15, 45, 90)
RETRYABLE_API_STATUS = {429, 500, 502, 503, 504}
BLOCK_STATUS_CODES = {403, 429, 503}
# Text that only appears on challenge/block pages, not on normal pages.
BLOCK_MARKERS = (
    "Just a moment...",
    "Attention Required! | Cloudflare",
    "cf-chl-",
    "Verify you are human",
    "Enable JavaScript and cookies to continue",
)


class WebDataError(Exception):
    """The Web Data API call itself failed (bad key, quota, network)."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class AccessBlockedError(Exception):
    """The site returned a block or challenge; stop rather than retry."""


class RobotsDisallowedError(AccessBlockedError):
    """robots.txt disallows the URL; callers stop the same way."""


def load_env_file(path=ENV_PATH):
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if key.strip() and value:
            os.environ.setdefault(key.strip(), value)


def _api_settings():
    load_env_file()
    key = os.environ.get("WEBDATA_API_KEY", "").strip()
    if not key:
        raise WebDataError("WEBDATA_API_KEY is not set. Add it to .env (see .env.example).")
    override = os.environ.get("WEBDATA_API_URL", "").strip()
    if _is_basic_token(key):
        token = key[6:].strip() if key.lower().startswith("basic ") else key
        return override or BASIC_TOKEN_URL, f"Basic {token}"
    return override or API_KEY_URL, f"Bearer {key}"


def _is_basic_token(key):
    """True for the older base64 "user:password" token, false for an API key."""
    if key.lower().startswith("basic "):
        return True
    try:
        return ":" in base64.b64decode(key, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False


def _scrape(url):
    """Send one URL to the API, retrying transient failures; return status code and HTML."""
    for attempt, delay in enumerate((*RETRY_DELAYS_SECONDS, None), 1):
        try:
            return _scrape_once(url)
        except WebDataError as exc:
            if delay is None or not exc.retryable:
                raise
            print(f"  Web Data API attempt {attempt} failed ({exc}); retrying in {delay} s")
            time.sleep(delay)


def _scrape_once(url):
    api_url, auth = _api_settings()
    body = {"target": "universal", "url": url}
    if os.environ.get("WEBDATA_JS_RENDER", "").strip() == "1":
        body["headless"] = "html"
    request = Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": auth, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise WebDataError(f"Web Data API returned HTTP {exc.code} for {url}: {detail}",
                           retryable=exc.code in RETRYABLE_API_STATUS) from exc
    except (URLError, OSError, HTTPException, ValueError) as exc:
        # Connection reset, timeout, truncated or garbled response: worth another try.
        raise WebDataError(f"Web Data API request failed for {url}: {type(exc).__name__}: {exc}",
                           retryable=True) from exc
    result = payload["results"][0]
    return int(result.get("status_code") or 0), result.get("content") or ""


def is_block_page(status_code, html):
    head = html[:5000]
    return status_code in BLOCK_STATUS_CODES or any(marker in head for marker in BLOCK_MARKERS)


# -- robots.txt ---------------------------------------------------------------
# urllib.robotparser ignores "*" and "$" wildcards, which sites such as Clutch
# rely on (e.g. "Disallow: /*?*hourly_rate=*"), so this is a small matcher that
# follows RFC 9309: longest match wins, Allow wins ties.

_robots_cache = {}


def parse_robots(text, agent="*"):
    """Return (allow, pattern) rules from the groups that apply to `agent`."""
    rules = []
    group_agents = []
    in_rules = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if in_rules:
                group_agents, in_rules = [], False
            group_agents.append(value.lower())
        elif field in ("allow", "disallow"):
            in_rules = True
            if agent.lower() in group_agents and value:
                rules.append((field == "allow", value))
    return rules


def _pattern_regex(pattern):
    anchored = pattern.endswith("$")
    body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def robots_allows(rules, url):
    parts = urlsplit(url)
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    best_len, allowed = -1, True
    for allow, pattern in rules:
        if _pattern_regex(pattern).match(target):
            if len(pattern) > best_len or (len(pattern) == best_len and allow):
                best_len, allowed = len(pattern), allow
    return allowed


def _robots_rules(url):
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots_cache:
        robots_url = f"{origin}/robots.txt"
        text = None
        try:
            with urlopen(robots_url, timeout=15) as response:
                direct = response.read().decode("utf-8", "replace")
            if not is_block_page(200, direct):
                text = direct
        except (URLError, TimeoutError):
            pass  # sites behind Cloudflare often block this; try via the API
        if text is None:
            status, content = _scrape(robots_url)
            if status != 200 or is_block_page(status, content):
                raise RobotsDisallowedError(f"Could not read {robots_url}; refusing to fetch without it.")
            text = content
        _robots_cache[origin] = parse_robots(text)
    return _robots_cache[origin]


def fetch_html(url, respect_robots=True):
    """Return the raw HTML of `url`, fetched through the Web Data API.

    respect_robots=False skips the robots.txt check for a URL the project owner
    has chosen to fetch anyway (the Clutch filter link); block detection stays on.
    """
    if respect_robots and not robots_allows(_robots_rules(url), url):
        raise RobotsDisallowedError(f"robots.txt disallows {url}. Stopping; use an allowed URL.")
    status, html = _scrape(url)
    if is_block_page(status, html):
        raise AccessBlockedError(f"The site returned a block/challenge (HTTP {status}) for {url}. Stopping.")
    if status >= 400:
        raise WebDataError(f"The site returned HTTP {status} for {url}")
    return html
