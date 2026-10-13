"""SQLite persistence for proxy state and request-attempt history."""
import json
import os
import sqlite3
from time import time

from app.models import ProxyState


class ProxyDatabase:
    """Small SQLite repository; uses only the Python standard library."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS proxy_states (
                    name TEXT PRIMARY KEY, host TEXT NOT NULL, port INTEGER NOT NULL,
                    healthy INTEGER NOT NULL, latency_ms REAL,
                    consecutive_failures INTEGER NOT NULL, total_checks INTEGER NOT NULL,
                    successful_checks INTEGER NOT NULL, last_checked_at REAL,
                    last_error TEXT, disabled INTEGER NOT NULL, cooldown_until REAL)"""
            )
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS request_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
                    attempt INTEGER NOT NULL, proxy TEXT NOT NULL, status INTEGER,
                    transport_ok INTEGER NOT NULL, proxy_header TEXT, error TEXT,
                    created_at REAL NOT NULL, details_json TEXT)"""
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_request_events_request_id "
                "ON request_events(request_id)"
            )

    def save_proxy(self, proxy: ProxyState) -> None:
        values = (
            proxy.name, proxy.host, proxy.port, int(proxy.healthy), proxy.latency_ms,
            proxy.consecutive_failures, proxy.total_checks, proxy.successful_checks,
            proxy.last_checked_at, proxy.last_error, int(proxy.disabled), proxy.cooldown_until,
        )
        with self._connection:
            self._connection.execute(
                """INSERT INTO proxy_states (
                    name, host, port, healthy, latency_ms, consecutive_failures,
                    total_checks, successful_checks, last_checked_at, last_error,
                    disabled, cooldown_until
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    host=excluded.host, port=excluded.port, healthy=excluded.healthy,
                    latency_ms=excluded.latency_ms,
                    consecutive_failures=excluded.consecutive_failures,
                    total_checks=excluded.total_checks,
                    successful_checks=excluded.successful_checks,
                    last_checked_at=excluded.last_checked_at,
                    last_error=excluded.last_error, disabled=excluded.disabled,
                    cooldown_until=excluded.cooldown_until""",
                values,
            )

    def load_proxy_states(self) -> dict[str, dict]:
        rows = self._connection.execute("SELECT * FROM proxy_states").fetchall()
        return {row["name"]: dict(row) for row in rows}

    def save_event(self, event: dict) -> None:
        with self._connection:
            self._connection.execute(
                """INSERT INTO request_events (
                    request_id, attempt, proxy, status, transport_ok,
                    proxy_header, error, created_at, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["request_id"], event["attempt"], event.get("proxy", ""),
                    event.get("status"), int(bool(event.get("transport_ok"))),
                    event.get("proxy_header"), event.get("error"), time(),
                    json.dumps(event, sort_keys=True),
                ),
            )

    def load_events(self, limit: int = 5000) -> list[dict]:
        rows = self._connection.execute(
            "SELECT details_json FROM request_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [json.loads(row["details_json"]) for row in reversed(rows)]

    def next_request_id(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(request_id), 0) AS latest FROM request_events"
        ).fetchone()
        return int(row["latest"])

    def close(self) -> None:
        self._connection.close()
