"""Coordinates health checks, selection, bounded retries, and request metrics."""
from app.config import TARGET_HOSTNAME, TARGET_PORT, MAX_RETRIES_PER_REQUEST
from app.health_checker import check_proxy
from app.models import ProxyState
from app.request_client import get_via_proxy
from app.selector import NoHealthyProxyError, RoundRobinSelector


class ProxyManager:
    def __init__(self, proxies):
        self.proxies = list(proxies)
        self.selector = RoundRobinSelector()
        self.events = []
        self.request_number = 0

    @property
    def target_url(self):
        return f"http://{TARGET_HOSTNAME}:{TARGET_PORT}"

    def refresh_health(self):
        print("\\nHealth check:")
        for proxy in self.proxies:
            ok = check_proxy(proxy)
            state = "HEALTHY" if ok else "UNHEALTHY"
            latency = f"{proxy.latency_ms:.1f} ms" if proxy.latency_ms is not None else "n/a"
            print(f"  {proxy.name:10} {state:10} latency={latency}")
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
                if p.healthy and not p.disabled and p.name not in tried
            ]
            try:
                proxy = self.selector.select(eligible)
            except NoHealthyProxyError as exc:
                last_error = str(exc)
                break

            tried.add(proxy.name)
            try:
                status, body, proxy_header = get_via_proxy(proxy, url)
                self.events.append({
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
                return status, body
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                proxy.record_check(False, error=last_error)
                self.events.append({
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

        raise RuntimeError(
            f"Request {request_id} could not be completed. Last error: {last_error}"
        )

    def print_summary(self):
        print("\\nProxy summary")
        print("-" * 72)
        print(f"{'Name':10} {'Status':12} {'Checks':>7} {'Success %':>10} {'Failures':>9}")
        for proxy in self.proxies:
            status = "healthy" if proxy.healthy else "unhealthy"
            print(
                f"{proxy.name:10} {status:12} {proxy.total_checks:7} "
                f"{proxy.success_rate:9.1f}% {proxy.consecutive_failures:9}"
            )
        successful = sum(1 for event in self.events if event.get("transport_ok"))
        print(f"\\nRequests attempted: {self.request_number}")
        print(f"Successful transport attempts: {successful}")
