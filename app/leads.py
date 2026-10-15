"""Clutch lead pipeline: listing -> company websites -> Excel tracker.

    py -m app.leads scrape --max-pages 1   Clutch listing pages -> data/leads.sqlite3 + output/clutch_companies.csv
    py -m app.leads enrich --limit 5       contact details from each company's own website (CSV updated)
    py -m app.leads enrich --api-fallback  same, but sites that block bots are fetched via the Web Data API
    py -m app.leads export                 output/clutch_companies.csv + output/clutch_outreach_tracker.xlsx
    py -m app.leads run --max-pages 1      all three in order
    py -m app.leads status                 what is stored so far
    py -m app.leads test-site URL          try the website step on one site, store nothing
"""
import argparse
import random
import sys
import time

from app.clutch_parser import build_page_url, extract_company_rows, get_total_pages
from app.leads_db import LeadsDatabase
from app.leads_export import write_csv, write_tracker
from app.webdata_client import AccessBlockedError, WebDataError, fetch_html
from app.website_contacts import WebsiteContactFinder

# The listing is fetched from this exact filter link (rate bands $50/hr and up),
# as requested. Clutch's robots.txt disallows "?hourly_rate=" URLs; the project
# owner chose to fetch it anyway, so the robots check is skipped for this link
# only. Block/challenge detection still stops the scrape.
LISTING_URL = (
    "https://clutch.co/developers/artificial-intelligence"
    "?hourly_rate=150-199&hourly_rate=100-149&hourly_rate=300"
    "&hourly_rate=200-300&hourly_rate=50-99"
)


def scrape(db, max_pages=None, min_delay=8.0, max_delay=15.0, reset=False):
    """Fetch listing pages, then save the CSV. Returns False if it had to stop."""
    try:
        return _scrape_pages(db, max_pages, min_delay, max_delay, reset)
    finally:
        print(f"CSV saved: {write_csv(db.all_companies())}")


def _scrape_pages(db, max_pages, min_delay, max_delay, reset):
    if reset:
        db.reset_progress(LISTING_URL)
    page = db.last_completed_page(LISTING_URL) + 1
    total_pages = None
    while total_pages is None or page <= total_pages:
        url = build_page_url(LISTING_URL, page)
        try:
            html = fetch_html(url, respect_robots=False)
        except (AccessBlockedError, WebDataError) as exc:
            print(f"Stopped at page {page}: {exc}")
            print("Progress is saved; run scrape again later to resume.")
            return False
        if total_pages is None:
            listing_pages = get_total_pages(html, fallback=page)
            total_pages = listing_pages
            if max_pages is not None:
                total_pages = min(total_pages, page + max_pages - 1)
            print(f"Listing has {listing_pages} pages; this run: {page} to {total_pages}")
        cards = extract_company_rows(html, url, page)
        if not cards:
            print(f"Page {page}: zero company cards. Stopping; check access or markup before continuing.")
            return False
        db.upsert_listing_rows(cards)  # every company the link shows, sponsored cards included
        db.save_progress(LISTING_URL, page)
        print(f"Page {page}/{total_pages}: {len(cards)} companies")
        page += 1
        if page <= total_pages:
            time.sleep(random.uniform(min_delay, max_delay))
    return True


def _print_contacts(result):
    print(f"    status: {result['enrichment_status']} {result['enrichment_error']}".rstrip())
    for label, field in (("emails", "emails"), ("phones", "phones"), ("people", "decision_makers"),
                         ("linkedin", "linkedin")):
        if result[field]:
            print(f"    {label}: {'; '.join(list(result[field])[:4])}")
    if result["contact_form_url"]:
        print(f"    contact form: {result['contact_form_url']}")


def enrich(db, limit=None, delay=2.0, max_pages=6, retry_failed=False, use_llm=True, api_fallback=False):
    finder = WebsiteContactFinder(delay=delay, max_pages=max_pages, use_llm=use_llm, api_fallback=api_fallback)
    companies = db.pending_companies(limit=limit, retry_failed=retry_failed)
    print(f"Companies to check: {len(companies)}" + (" (Web Data API fallback on)" if api_fallback else ""))
    try:
        _enrich_companies(db, finder, companies)
    finally:
        print(f"CSV saved: {write_csv(db.all_companies())}")
        if api_fallback:
            print(f"Web Data API requests used for blocked sites: {finder.api_requests}")


def _enrich_companies(db, finder, companies):
    for index, company in enumerate(companies, 1):
        print(f"[{index}/{len(companies)}] {company['agency_name']} - {company['website'] or 'no website'}")
        try:
            result = finder.find(company["website"])
        except Exception as exc:  # one bad site must not end the whole run
            result = {"enrichment_status": "error", "enrichment_error": f"{type(exc).__name__}: {exc}"[:200]}
        db.save_contacts(company["company_key"], result)
        if "emails" in result:
            _print_contacts(result)
        else:
            print(f"    status: error {result['enrichment_error']}")


def export(db):
    companies = db.all_companies()
    print(f"CSV saved: {write_csv(companies)}")
    print(f"Excel tracker written: {write_tracker(companies)}")


def status(db):
    companies = db.all_companies()
    print(f"Companies stored: {len(companies)}  (listing: {LISTING_URL})")
    print(f"Listing pages completed: {db.last_completed_page(LISTING_URL)}")
    for name, count in sorted(db.status_counts().items()):
        print(f"  {name:12} {count}")
    with_email = sum(1 for company in companies if company["emails"])
    with_person = sum(1 for company in companies if company["decision_makers"])
    print(f"With an email: {with_email}; with an owner/founder name: {with_person}")


def main():
    # Company names can hold characters the Windows console cannot show; never crash on them.
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["scrape", "enrich", "export", "run", "status", "test-site"])
    parser.add_argument("url", nargs="?", help="test-site: company website to check")
    parser.add_argument("--max-pages", type=int, default=None, help="scrape: listing pages this run")
    parser.add_argument("--min-delay", type=float, default=8.0, help="scrape: min seconds between listing pages")
    parser.add_argument("--max-delay", type=float, default=15.0, help="scrape: max seconds between listing pages")
    parser.add_argument("--reset", action="store_true", help="scrape: start again from listing page 1")
    parser.add_argument("--limit", type=int, default=None, help="enrich: companies this run")
    parser.add_argument("--site-delay", type=float, default=2.0, help="enrich: seconds between pages of a site")
    parser.add_argument("--site-pages", type=int, default=6, help="enrich: max pages per company site")
    parser.add_argument("--retry-failed", action="store_true", help="enrich: retry blocked/error companies")
    parser.add_argument("--no-llm", action="store_true", help="enrich: skip the local LLM step")
    parser.add_argument("--api-fallback", action="store_true",
                        help="enrich/test-site: fetch sites that block bots through the Web Data API "
                             "(1 API request per page)")
    args = parser.parse_args()
    if args.min_delay < 0 or args.max_delay < args.min_delay:
        parser.error("Delays must satisfy 0 <= --min-delay <= --max-delay")
    for name in ("max_pages", "limit"):
        if getattr(args, name) is not None and getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be >= 1")

    if args.command == "test-site":
        if not args.url:
            parser.error("test-site needs a website URL")
        finder = WebsiteContactFinder(delay=args.site_delay, max_pages=args.site_pages,
                                      use_llm=not args.no_llm, api_fallback=args.api_fallback)
        result = finder.find(args.url)
        _print_contacts(result)
        print(f"    pages read: {'; '.join(result['contact_source_urls']) or 'none'}")
        if args.api_fallback:
            print(f"    Web Data API requests used: {finder.api_requests}")
        return

    db = LeadsDatabase()
    try:
        if args.command in ("scrape", "run"):
            ok = scrape(db, args.max_pages, args.min_delay, args.max_delay, args.reset)
            if not ok and args.command == "scrape":
                raise SystemExit(1)
        if args.command in ("enrich", "run"):
            enrich(db, args.limit, args.site_delay, args.site_pages, args.retry_failed, not args.no_llm,
                   args.api_fallback)
        if args.command in ("export", "run"):
            export(db)
        if args.command == "status":
            status(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
