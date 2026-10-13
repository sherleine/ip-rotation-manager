"""Health checks for configured HTTP proxy endpoints."""
from time import perf_counter
from urllib.request import ProxyHandler, build_opener

from app.config import HEALTH_PATH, HEALTH_TIMEOUT_SECONDS, TARGET_HOSTNAME, TARGET_PORT
from app.models import ProxyState


def check_proxy(proxy: ProxyState) -> bool:
    """Check a mock proxy by fetching the lab target's /health endpoint."""
    started = perf_counter()
    url = f"http://{TARGET_HOSTNAME}:{TARGET_PORT}{HEALTH_PATH}"
    try:
        opener = build_opener(ProxyHandler({"http": proxy.url, "https": proxy.url}))
        with opener.open(url, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            payload = response.read(256).decode("utf-8", "replace").strip()
            ok = response.status == 200 and payload == "ok"
        elapsed_ms = (perf_counter() - started) * 1000
        proxy.record_check(ok, elapsed_ms if ok else None,
                           None if ok else "Unexpected health response")
        return ok
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        proxy.record_check(False, elapsed_ms, f"{type(exc).__name__}: {exc}")
        return False
