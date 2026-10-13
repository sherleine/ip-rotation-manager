"""Coordinates health checks, selection, bounded retries, and persistent metrics."""
from app.config import (
    DATABASE_PATH, MAX_CONSECUTIVE_FAILURES, MAX_RETRIES_PER_REQUEST,
    RECOVERY_COOLDOWN_SECONDS, TARGET_HOSTNAME, TARGET_PORT,
)
from app.database import ProxyDatabase
from app.health_checker import check_proxy
from app.models import ProxyState
from app.request_client import get_via_proxy
from app.selector import NoHealthyProxyError, RoundRobinSelector


class ProxyManager:
    def __init__(self, proxies, db_path=DATABASE_PATH):
        self.proxies = list(proxies)
        self.selector = RoundRobinSelector()
        self.database = ProxyDatabase(db_path)
        self.events = self.database.load_events()
        self.request_number = self.database.next_request_id()

        saved = self.database.load_proxy_states()
        for proxy in self.proxies:
            state = saved.get(proxy.name)
            if state and state["host"] == proxy.host and state["port"] == proxy.port:
                for field in (
                    "healthy", "latency_ms", "consecutive_failures", "total_checks",
                    "successful_checks", "last_checked_at", "last_error", "disabled",
                    "cooldown_until",
                ):
                    value = state[field]
                    if field in ("healthy", "disabled"):
                        value = bool(value)
                    setattr(proxy, field, value)
            self.database.save_proxy(proxy)

    @property
    def target_url(self):
        return f"http://{TARGET_HOSTNAME}:{TARGET_PORT}"

    def _record_event(self, event):
        self.events.append(event)
        self.database.save_event(event)

    def _save_proxies(self):
        for proxy in self.proxies:
            self.database.save_proxy(proxy)

    def refresh_health(self):
        print("\nHealth check:")
        for proxy in self.proxies:
            if proxy.disabled:
                state = "DISABLED"
            elif proxy.in_cooldown():
                state = "COOLDOWN"
            else:
                ok = check_proxy(proxy)
                state = "HEALTHY" if ok else "UNHEALTHY"
            latency = f"{proxy.latency_ms:.1f} ms" if proxy.latency_ms is not None else "n/a"
            print(f"  {proxy.name:10} {state:10} latency={latency}")
            self.database.save_proxy(proxy)
        print()

    def request(self, path="/"):
        """Make one request and try each eligible proxy at most once."""
        self.request_number += 1
        request_id = self.request_number
        url = self.target_url + path
        tried = set()
        last_error = None
        attempt_limit = min(MAX_RETRIES_PER_REQUEST, len(self.proxies))

        for attempt_number in range(1, attempt_limit + 1):
            eligible = [
                p for p in self.proxies
                if p.healthy and not p.disabled and not p.in_cooldown()
                and p.name not in tried
            ]
            try:
                proxy = self.selector.select(eligible)
            except NoHealthyProxyError as exc:
                last_error = str(exc)
                break

            tried.add(proxy.name)
            try:
                status, body, proxy_header = get_via_proxy(proxy, url)
                self._record_event({
                    "request_id": request_id,
                    "attempt": attempt_number,
                    "proxy": proxy.name,
                    "status": status,
                    "transport_ok": True,
                    "proxy_header": proxy_header,
                })
                print(
                    f"Request {request_id}, attempt {attempt_number}: "
                    f"{proxy.name} -> HTTP {status}; "
                    f"proxy header={proxy_header or 'not supplied'}"
                )
                # An HTTP 4xx/5xx response is not automatically a proxy transport failure.
                self._save_proxies()
                return status, body
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                proxy.record_check(
                    False,
                    error=last_error,
                    cooldown_seconds=RECOVERY_COOLDOWN_SECONDS,
                    cooldown_threshold=MAX_CONSECUTIVE_FAILURES,
                )
                self.database.save_proxy(proxy)
                self._record_event({
                    "request_id": request_id,
                    "attempt": attempt_number,
                    "proxy": proxy.name,
                    "status": None,
                    "transport_ok": False,
                    "error": last_error,
                })
                print(
                    f"Request {request_id}, attempt {attempt_number}: "
                    f"{proxy.name} failed: {last_error}"
                )

        self._save_proxies()
        raise RuntimeError(
            f"Request {request_id} could not be completed. Last error: {last_error}"
        )

    def print_summary(self):
        print("\nProxy summary")
        print("-" * 72)
        print(f"{'Name':10} {'Status':12} {'Checks':>7} {'Success %':>10} {'Failures':>9}")
        for proxy in self.proxies:
            if proxy.disabled:
                status = "disabled"
            elif proxy.in_cooldown():
                status = "cooldown"
            else:
                status = "healthy" if proxy.healthy else "unhealthy"
            print(
                f"{proxy.name:10} {status:12} {proxy.total_checks:7} "
                f"{proxy.success_rate:9.1f}% {proxy.consecutive_failures:9}"
            )
        successful = sum(1 for event in self.events if event.get("transport_ok"))
        print(f"\nRequest IDs recorded (latest): {self.request_number}")
        print(f"Successful transport attempts in retained history: {successful}")

    def close(self):
        self._save_proxies()
        self.database.close()
