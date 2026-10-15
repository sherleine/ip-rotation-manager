"""SQLite store for Clutch companies and the contact details found on their sites."""
import sqlite3
from pathlib import Path
from time import time

LEADS_DB_PATH = "data/leads.sqlite3"

LISTING_FIELDS = (
    "agency_name", "country", "city", "website", "main_services", "secondary_services",
    "team_size_raw", "hourly_rate_raw", "min_project_size_raw", "rating", "review_count",
    "description", "source_url", "page_number",
)
CONTACT_FIELDS = (
    "emails", "phones", "decision_makers", "linkedin", "contact_form_url",
    "contact_source_urls", "enrichment_status", "enrichment_error",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    company_key TEXT PRIMARY KEY,
    profile_link TEXT NOT NULL DEFAULT '',
    agency_name TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    main_services TEXT NOT NULL DEFAULT '',
    secondary_services TEXT NOT NULL DEFAULT '',
    team_size_raw TEXT NOT NULL DEFAULT '',
    hourly_rate_raw TEXT NOT NULL DEFAULT '',
    min_project_size_raw TEXT NOT NULL DEFAULT '',
    rating TEXT NOT NULL DEFAULT '',
    review_count TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    page_number TEXT NOT NULL DEFAULT '',
    emails TEXT NOT NULL DEFAULT '',
    phones TEXT NOT NULL DEFAULT '',
    decision_makers TEXT NOT NULL DEFAULT '',
    linkedin TEXT NOT NULL DEFAULT '',
    contact_form_url TEXT NOT NULL DEFAULT '',
    contact_source_urls TEXT NOT NULL DEFAULT '',
    enrichment_status TEXT NOT NULL DEFAULT 'pending',
    enrichment_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS listing_progress (
    base_url TEXT PRIMARY KEY,
    last_completed_page INTEGER NOT NULL
);
"""


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(item) for item in value if item)
    return str(value).strip()


def company_key(row):
    profile = _text(row.get("profile_link")).rstrip("/").casefold()
    return f"profile:{profile}" if profile else f"name:{_text(row.get('agency_name')).casefold()}"


class LeadsDatabase:
    def __init__(self, path=LEADS_DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self):
        self.connection.close()

    def upsert_listing_rows(self, rows):
        """Insert new companies; refresh listing fields of known ones, keep contacts."""
        now = time()
        with self.connection:
            for row in rows:
                if not _text(row.get("agency_name")):
                    continue
                values = {field: _text(row.get(field)) for field in LISTING_FIELDS}
                columns = ", ".join(LISTING_FIELDS)
                placeholders = ", ".join(f":{field}" for field in LISTING_FIELDS)
                updates = ", ".join(f"{field}=excluded.{field}" for field in LISTING_FIELDS)
                self.connection.execute(
                    f"""INSERT INTO companies (company_key, profile_link, {columns}, created_at, updated_at)
                        VALUES (:company_key, :profile_link, {placeholders}, :now, :now)
                        ON CONFLICT(company_key) DO UPDATE SET {updates}, updated_at=excluded.updated_at""",
                    {**values, "company_key": company_key(row),
                     "profile_link": _text(row.get("profile_link")), "now": now},
                )

    def pending_companies(self, limit=None, retry_failed=False):
        statuses = ("pending", "error", "blocked") if retry_failed else ("pending",)
        query = (f"SELECT * FROM companies WHERE enrichment_status IN ({','.join('?' * len(statuses))}) "
                 "ORDER BY created_at, company_key")
        params = list(statuses)
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return [dict(row) for row in self.connection.execute(query, params)]

    def save_contacts(self, key, contacts):
        values = {field: _text(contacts.get(field)) for field in CONTACT_FIELDS}
        assignments = ", ".join(f"{field}=:{field}" for field in CONTACT_FIELDS)
        with self.connection:
            self.connection.execute(
                f"UPDATE companies SET {assignments}, updated_at=:now WHERE company_key=:key",
                {**values, "now": time(), "key": key},
            )

    def all_companies(self):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM companies ORDER BY created_at, company_key")]

    def status_counts(self):
        return dict(self.connection.execute(
            "SELECT enrichment_status, COUNT(*) FROM companies GROUP BY enrichment_status").fetchall())

    def last_completed_page(self, base_url):
        row = self.connection.execute(
            "SELECT last_completed_page FROM listing_progress WHERE base_url=?", (base_url,)).fetchone()
        return row[0] if row else 0

    def save_progress(self, base_url, page):
        with self.connection:
            self.connection.execute(
                """INSERT INTO listing_progress (base_url, last_completed_page) VALUES (?, ?)
                   ON CONFLICT(base_url) DO UPDATE SET last_completed_page=excluded.last_completed_page""",
                (base_url, page),
            )

    def reset_progress(self, base_url):
        with self.connection:
            self.connection.execute("DELETE FROM listing_progress WHERE base_url=?", (base_url,))
