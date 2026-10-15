"""Rotation manager for raw residential/mobile proxies.

Responsibilities:
  - hand the scraper a usable proxy (rotating or sticky) via acquire()
  - record what happened via report(), and retire ("burn") banned sessions
  - track bandwidth so the per-GB cost is visible as it adds up

It deliberately does NOT make the HTTP request itself. The scraper owns the
request (requests / httpx / cloudscraper / Playwright); this class owns
selection, session lifecycle, and health/cost accounting. That split is what
lets the same manager serve a plain-HTTP scraper or a browser-based one, sync
or threaded (acquire/report are fast in-memory ops under a lock).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Dict, Optional

from app.providers import ProxyProvider, ProxyEndpoint


class Outcome(str, Enum):
    OK = "ok"                      # got the content we wanted
    SOFT_BLOCK = "soft_block"      # 200 but captcha / "just a moment" / block page
    RATE_LIMITED = "rate_limited"  # 429
    FORBIDDEN = "forbidden"        # 403
    ERROR = "error"                # timeout / connection reset / etc.


# Outcomes that mean "this exit IP is burned for this site" -> retire it so the
# next acquire() mints a fresh IP.
_BURN = {Outcome.SOFT_BLOCK, Outcome.FORBIDDEN, Outcome.RATE_LIMITED}


@dataclass
class Session:
    id: str
    endpoint: ProxyEndpoint
    domain: str
    geo: Optional[str]
    created_at: float
    ttl_seconds: float
    sticky: bool
    successes: int = 0
    failures: int = 0
    bytes_used: int = 0
    burned: bool = False

    def expired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now - self.created_at >= self.ttl_seconds

    def usable(self, now: Optional[float] = None) -> bool:
        return not self.burned and not self.expired(now)


@dataclass
class DomainStats:
    requests: int = 0
    successes: int = 0
    soft_blocks: int = 0
    forbidden: int = 0
    rate_limited: int = 0
    errors: int = 0
    bytes_used: int = 0


class RotationManager:
    def __init__(
        self,
        provider: ProxyProvider,
        *,
        session_ttl_seconds: float = 540.0,  # ~9 min, under typical 10 min provider TTL
        cost_per_gb: float = 4.0,             # set to your plan's rate for a live estimate
    ):
        self.provider = provider
        self.session_ttl = session_ttl_seconds
        self.cost_per_gb = cost_per_gb
        self._sticky: Dict[str, Session] = {}   # (domain|geo) -> live sticky session
        self._stats: Dict[str, DomainStats] = {}
        self._lock = Lock()

    # -- public API the scraper uses ------------------------------------

    def acquire(self, domain: str, *, geo: Optional[str] = None,
                sticky: bool = True) -> Session:
        """Return a usable Session for this domain.

        sticky=True reuses one exit IP per (domain, geo) until it expires or is
        burned — use it for logins / multi-step flows / pagination.
        sticky=False mints a fresh rotating IP every call.
        """
        with self._lock:
            if sticky:
                key = f"{domain}|{geo or ''}"
                sess = self._sticky.get(key)
                if sess and sess.usable():
                    return sess
                sess = self._mint(domain, geo, sticky=True)
                self._sticky[key] = sess
                return sess
            return self._mint(domain, geo, sticky=False)

    def report(self, session: Session, outcome: Outcome,
               *, bytes_transferred: int = 0) -> None:
        """Tell the manager how the request went. Burns bad sessions."""
        with self._lock:
            stats = self._stats.setdefault(session.domain, DomainStats())
            stats.requests += 1
            stats.bytes_used += bytes_transferred
            session.bytes_used += bytes_transferred

            if outcome == Outcome.OK:
                session.successes += 1
                stats.successes += 1
            else:
                session.failures += 1
                if outcome == Outcome.SOFT_BLOCK:
                    stats.soft_blocks += 1
                elif outcome == Outcome.FORBIDDEN:
                    stats.forbidden += 1
                elif outcome == Outcome.RATE_LIMITED:
                    stats.rate_limited += 1
                else:
                    stats.errors += 1

            if outcome in _BURN:
                session.burned = True
                if session.sticky:
                    key = f"{session.domain}|{session.geo or ''}"
                    if self._sticky.get(key) is session:
                        del self._sticky[key]

    def release(self, session: Session) -> None:
        """Sticky sessions stay cached for reuse; rotating ones are transient."""
        return

    # -- introspection --------------------------------------------------

    def cost_estimate(self) -> float:
        gb = sum(st.bytes_used for st in self._stats.values()) / (1024 ** 3)
        return round(gb * self.cost_per_gb, 4)

    def summary(self) -> dict:
        out = {}
        for domain, st in self._stats.items():
            out[domain] = {
                "requests": st.requests,
                "success_rate": round(100 * st.successes / st.requests, 1) if st.requests else 0.0,
                "soft_blocks": st.soft_blocks,
                "forbidden": st.forbidden,
                "rate_limited": st.rate_limited,
                "errors": st.errors,
                "gb_used": round(st.bytes_used / (1024 ** 3), 6),
            }
        return out

    # -- internals ------------------------------------------------------

    def _mint(self, domain: str, geo: Optional[str], sticky: bool) -> Session:
        session_id = uuid.uuid4().hex[:12] if sticky else None
        endpoint = self.provider.endpoint(geo=geo, session_id=session_id)
        return Session(
            id=session_id or "rotating",
            endpoint=endpoint,
            domain=domain,
            geo=geo,
            created_at=time.time(),
            ttl_seconds=self.session_ttl,
            sticky=sticky,
        )
