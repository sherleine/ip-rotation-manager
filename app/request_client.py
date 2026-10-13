"""HTTP client that routes requests through a selected proxy."""
from urllib.request import ProxyHandler, build_opener

from app.config import REQUEST_TIMEOUT_SECONDS
from app.models import ProxyState


def get_via_proxy(proxy: ProxyState, url: str):
    opener = build_opener(ProxyHandler({"http": proxy.url, "https": proxy.url}))
    with opener.open(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = response.read(64 * 1024).decode("utf-8", "replace")
        return response.status, body, response.headers.get("X-Mock-Proxy")
