"""Find published business contact details on a company's own website.

Based on test_clutch/website_enrichment.py: it opens the homepage, follows
same-domain links that look like Contact / About / Team pages (contact first),
and extracts emails, phone numbers, the contact-form page, LinkedIn links and
owner/founder names. Company websites are fetched directly (no Web Data API
credits). It respects robots.txt, waits between requests, and stops on a site
that blocks or challenges it, unless api_fallback is on: then a blocked site
is fetched through the Web Data API instead (costs one API request per page).
"""
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app import llm_extract
from app.webdata_client import (
    AccessBlockedError,
    RobotsDisallowedError,
    WebDataError,
    fetch_html,
    is_block_page,
    parse_robots,
    robots_allows,
)

USER_AGENT = "CompanyResearchBot/1.0 (+https://github.com/sherleine/ip-rotation-manager)"
PAGE_TIMEOUT_SECONDS = 20
MAX_PAGE_BYTES = 3_000_000
# Lower number = visited earlier. Contact pages carry most of the details.
PAGE_TERMS = {
    "contact": 0, "get-in-touch": 0, "reach": 1, "about": 2, "team": 2, "leadership": 2,
    "founder": 2, "management": 3, "people": 3, "company": 4, "our-story": 4,
}
LANGUAGE_SEGMENT_RE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2})?$")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
JUNK_EMAIL_RE = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|css|js)$|@\dx\.|example\.|sentry|wixpress|@domain\.|@email\.|"
    r"yourname|your-?email|@sentry|noreply|no-reply",
    re.IGNORECASE,
)
ROLE_EMAIL_PREFIXES = ("info", "hello", "contact", "sales", "business", "office", "enquiries",
                       "inquiries", "partnerships", "hi", "team")
# Only phone numbers written in an explicit format: "+44 20 ..." or "(555) 123-4567".
# Separators are spaces, dots or dashes on one line, never a line break.
PHONE_TEXT_RE = re.compile(
    r"(?<![\w+])(?:\+\d{1,3}[  .-]?)?\(?\d{2,5}\)?[  .-]\d{2,5}[  .-]\d{2,5}(?:[  .-]\d{2,5})?(?!\w)"
)
TITLE_RE = re.compile(
    r"\b(co-?founder|founder|owner|ceo|chief executive officer|managing director|"
    r"president|managing partner|principal|cto|chief technology officer)\b",
    re.IGNORECASE,
)
# A title naming another organisation is a client testimonial, not this company's owner.
OTHER_COMPANY_TITLE_RE = re.compile(r"\bformer\b|\bex-|\bof\b|\bat\b|,|\bclient\b", re.IGNORECASE)
NAME_RE = re.compile(r"^[A-Z][a-zA-Z'.-]+(?: [A-Z][a-zA-Z'.-]+){1,3}$")
NOT_NAME_WORDS = {
    "our", "team", "about", "meet", "contact", "the", "company", "leadership", "founder",
    "founders", "ceo", "us", "services", "home", "careers", "read", "more", "learn", "view",
    "chief", "officer", "director", "managing", "president", "owner", "partner", "group",
    "solutions", "technologies", "digital", "agency", "studio", "labs", "inc", "ltd", "llc",
}


def normalize_url(value):
    value = (value or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return urldefrag(value)[0].rstrip("/")


def host_of(url):
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_domain(url, root):
    host, root_host = host_of(url), host_of(root)
    return bool(host and root_host and (host == root_host or host.endswith("." + root_host)))


def decode_cfemail(hex_string):
    """Decode Cloudflare's email obfuscation (data-cfemail / email-protection#...)."""
    try:
        data = bytes.fromhex(hex_string)
        return bytes(byte ^ data[0] for byte in data[1:]).decode("utf-8")
    except (ValueError, IndexError, UnicodeDecodeError):
        return ""


def looks_like_name(text):
    text = text.strip()
    if len(text) > 40 or not NAME_RE.match(text):
        return False
    return not any(word.lower().strip(".") in NOT_NAME_WORDS for word in text.split())


def find_decision_makers(lines):
    """Return "Name (Title)" for people shown next to an owner/founder-type title."""
    found = []
    for index, line in enumerate(lines):
        if len(line) > 90 or not TITLE_RE.search(line):
            continue
        name, title = "", line
        parts = re.split(r"\s*(?:,|\||–|—| - )\s*", line, maxsplit=1)
        if len(parts) == 2 and looks_like_name(parts[0]) and TITLE_RE.search(parts[1]):
            name, title = parts
        elif index > 0 and looks_like_name(lines[index - 1]):
            name = lines[index - 1]
        elif index + 1 < len(lines) and looks_like_name(lines[index + 1]):
            name = lines[index + 1]
        if not name or OTHER_COMPANY_TITLE_RE.search(title):
            continue  # client testimonials: "CTO, Acme Inc." / "Former CEO of ..."
        entry = f"{name.strip()} ({title.strip()[:60]})"
        if entry not in found:
            found.append(entry)
    return found[:5]


ROLE_ORDER = ("owner", "founder", "ceo", "chief executive", "managing director", "president",
              "managing partner", "principal", "cto", "chief technology")


def role_rank(entry):
    """Owners/founders first, then CEO, MD, president ... CTO last."""
    title = entry.rsplit("(", 1)[-1].lower()
    return next((index for index, role in enumerate(ROLE_ORDER) if role in title), len(ROLE_ORDER))


def unique_phones(phones):
    """Drop the same number written twice ("+1 (949) 620-0723" and "+19496200723")."""
    by_digits = {}
    for phone in sorted(phones, key=lambda value: (-len(value), value)):
        digits = re.sub(r"\D", "", phone)
        if not any(digits.endswith(seen) or seen.endswith(digits) for seen in by_digits):
            by_digits[digits] = phone
    return sorted(by_digits.values())


def extract_page_contacts(soup, page_url):
    """Pull contact details out of one parsed page."""
    emails, phones, linkedin = set(), set(), set()
    for tag in soup.select("[data-cfemail]"):
        emails.add(decode_cfemail(tag.get("data-cfemail", "")))
    for tag in soup.select("a[href]"):
        href = tag.get("href", "").strip()
        lower = href.lower()
        if lower.startswith("mailto:"):
            emails.add(unquote(href.split(":", 1)[1].split("?", 1)[0]))
        elif "/cdn-cgi/l/email-protection#" in lower:
            emails.add(decode_cfemail(href.rsplit("#", 1)[-1]))
        elif lower.startswith("tel:"):
            phones.add(re.sub(r"\s+", " ", unquote(href.split(":", 1)[1])).strip())
        elif "linkedin.com/company/" in lower or "linkedin.com/in/" in lower:
            linkedin.add(href.split("?", 1)[0].rstrip("/"))

    text = soup.get_text("\n", strip=True)
    emails.update(EMAIL_RE.findall(text))
    for match in PHONE_TEXT_RE.findall(text):
        digits = re.sub(r"\D", "", match)
        if 8 <= len(digits) <= 15 and (match.startswith(("+", "(")) or len(digits) >= 10):
            phones.add(match.strip())

    emails = {email.strip().lower() for email in emails if email and EMAIL_RE.fullmatch(email.strip())}
    emails = {email for email in emails if not JUNK_EMAIL_RE.search(email)}
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    has_form = any(
        form.select_one("textarea") or form.select_one('input[type="email"]')
        for form in soup.select("form")
    )
    return {
        "emails": emails,
        "phones": phones,
        "linkedin": linkedin,
        "decision_makers": find_decision_makers(lines),
        "contact_form": has_form and "contact" in page_url.lower(),
        "text": "\n".join(lines),
    }


def rank_emails(emails, website, people):
    """Order emails: matching a decision maker, then company-domain role inboxes, then the rest."""
    first_names = {person.split()[0].lower() for person in people if person}
    domain = host_of(website)

    def score(email):
        local, _, email_domain = email.partition("@")
        on_domain = email_domain == domain or email_domain.endswith("." + domain)
        if any(name and name in local for name in first_names):
            return (0, email)
        if on_domain and local.startswith(ROLE_EMAIL_PREFIXES):
            return (1, email)
        return (2 if on_domain else 3, email)

    return sorted(emails, key=score)


# Direct-fetch results that --api-fallback retries through the Web Data API.
# A robots.txt "Disallow" is never retried.
FALLBACK_STATUSES = {"blocked:robots_unavailable", "blocked:challenge", "blocked:http_401",
                     "blocked:http_403", "blocked:http_429", "blocked:http_503"}


class WebsiteContactFinder:
    def __init__(self, delay=2.0, max_pages=6, use_llm=True, api_fallback=False):
        self.delay = delay
        self.max_pages = max_pages
        self.use_llm = use_llm
        self.api_fallback = api_fallback
        self.api_requests = 0     # pages fetched through the Web Data API (each costs a request)
        self._api_origins = set()  # sites that blocked direct fetching; go straight to the API
        self._robots = {}

    def _open(self, url):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
        return urlopen(request, timeout=PAGE_TIMEOUT_SECONDS)

    def robots_rules(self, url):
        """Rules for the site, [] when it has no robots.txt, None when unreadable."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            try:
                with self._open(origin + "/robots.txt") as response:
                    text = response.read(500_000).decode("utf-8", "replace")
                self._robots[origin] = None if is_block_page(200, text) else parse_robots(text)
            except HTTPError as exc:
                self._robots[origin] = [] if exc.code in (404, 410) else None
            except (URLError, TimeoutError, OSError, ValueError):
                self._robots[origin] = None
        return self._robots[origin]

    def fetch(self, url):
        """Return (soup, final_url, status). status is "ok" or why it was skipped."""
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if origin in self._api_origins:
            return self._fetch_via_api(url)
        soup, final_url, status = self._fetch_direct(url)
        if soup is None and self.api_fallback and status in FALLBACK_STATUSES:
            soup, final_url, api_status = self._fetch_via_api(url)
            if soup is not None:
                self._api_origins.add(origin)
            return soup, final_url, api_status
        return soup, final_url, status

    def _fetch_via_api(self, url):
        time.sleep(self.delay)
        try:
            html = fetch_html(url)  # checks robots.txt itself, then fetches through the API
        except RobotsDisallowedError:
            return None, url, "blocked:robots_disallow"
        except AccessBlockedError:
            return None, url, "blocked:api_challenge"
        except WebDataError as exc:
            return None, url, f"error:api {str(exc)[:80]}"
        self.api_requests += 1
        return BeautifulSoup(html, "lxml"), url, "ok"

    def _fetch_direct(self, url):
        rules = self.robots_rules(url)
        if rules is None:
            return None, url, "blocked:robots_unavailable"
        if not robots_allows(rules, url):
            return None, url, "blocked:robots_disallow"
        time.sleep(self.delay)
        try:
            with self._open(url) as response:
                final_url = response.geturl()
                if "html" not in response.headers.get("Content-Type", "").lower():
                    return None, final_url, "skipped:not_html"
                charset = response.headers.get_content_charset() or "utf-8"
                html = response.read(MAX_PAGE_BYTES).decode(charset, "replace")
        except HTTPError as exc:
            if exc.code in (401, 403, 429, 503):
                return None, url, f"blocked:http_{exc.code}"
            return None, url, f"skipped:http_{exc.code}"
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            return None, url, f"error:{type(exc).__name__}"
        if is_block_page(200, html):
            return None, final_url, "blocked:challenge"
        return BeautifulSoup(html, "lxml"), final_url, "ok"

    def find(self, website):
        """Crawl one company website; return the fields LeadsDatabase.save_contacts expects."""
        root = normalize_url(website)
        result = {"emails": set(), "phones": set(), "linkedin": set(), "decision_makers": [],
                  "contact_form_url": "", "contact_source_urls": [],
                  "enrichment_status": "completed", "enrichment_error": ""}
        if not root:
            result.update(enrichment_status="no_website", enrichment_error="missing_website")
            return result

        queue, queued, visited = [(-1, root)], {root}, set()
        seen_page_names = set()
        llm_text = []
        while queue and len(visited) < self.max_pages:
            queue.sort()
            _, url = queue.pop(0)
            visited.add(url)
            soup, final_url, status = self.fetch(url)
            if soup is None:
                if status.startswith("blocked") or (url == root and status.startswith("error")):
                    result.update(enrichment_status="blocked" if status.startswith("blocked") else "error",
                                  enrichment_error=status)
                    break
                continue
            if not same_domain(final_url, root):
                if url != root:
                    continue  # a link that redirected off the company's own site
                parts = urlsplit(final_url)
                root = f"{parts.scheme}://{parts.netloc}"  # homepage moved to a new domain

            page = extract_page_contacts(soup, final_url)
            result["emails"] |= page["emails"]
            result["phones"] |= page["phones"]
            result["linkedin"] |= page["linkedin"]
            for person in page["decision_makers"]:
                if person not in result["decision_makers"]:
                    result["decision_makers"].append(person)
            if page["contact_form"] and not result["contact_form_url"]:
                result["contact_form_url"] = final_url
            result["contact_source_urls"].append(final_url)
            if url != root:
                llm_text.append(page["text"])

            for tag in soup.select("a[href]"):
                href = (tag.get("href") or "").strip()
                if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                    continue
                target = normalize_url(urljoin(final_url, href))
                if not target or target in queued or not same_domain(target, root):
                    continue
                segments = [part for part in urlsplit(target).path.lower().split("/") if part]
                if segments and LANGUAGE_SEGMENT_RE.match(segments[0]):
                    continue  # /de/contact, /fr-fr/about: translated copies of the same pages
                page_name = segments[-1] if segments else ""
                if page_name in seen_page_names:
                    continue
                seen_page_names.add(page_name)
                label = f"{tag.get_text(' ', strip=True)} {urlsplit(target).path}".lower()
                priorities = [rank for term, rank in PAGE_TERMS.items() if term in label]
                if priorities:
                    queue.append((min(priorities), target))
                    queued.add(target)

        if result["enrichment_status"] == "completed" and any(
                "{0.scheme}://{0.netloc}".format(urlsplit(page)) in self._api_origins
                for page in result["contact_source_urls"]):
            result["enrichment_error"] = "via_web_data_api"
        if self.use_llm and llm_text and llm_extract.is_configured():
            for person in llm_extract.find_decision_makers("\n\n".join(llm_text)):
                if person not in result["decision_makers"]:
                    result["decision_makers"].append(person)

        result["decision_makers"].sort(key=role_rank)
        names = [entry.split(" (", 1)[0] for entry in result["decision_makers"]]
        result["emails"] = rank_emails(result["emails"], root, names)
        result["phones"] = unique_phones(result["phones"])
        result["linkedin"] = sorted(result["linkedin"])
        if result["enrichment_status"] == "completed" and not (
                result["emails"] or result["phones"] or result["contact_form_url"] or result["decision_makers"]):
            result["enrichment_status"] = "not_found"
        return result
