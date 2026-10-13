"""Proxy selection policies."""
from typing import Iterable

from app.models import ProxyState


class NoHealthyProxyError(RuntimeError):
    """Raised when all configured proxy endpoints are unavailable."""


class RoundRobinSelector:
    """Selects eligible endpoints in round-robin order."""

    def __init__(self) -> None:
        self._last_index = -1

    def select(self, proxies: Iterable[ProxyState]) -> ProxyState:
        eligible = [p for p in proxies if p.healthy and not p.disabled]
        if not eligible:
            raise NoHealthyProxyError("No healthy proxy endpoints are available.")
        self._last_index = (self._last_index + 1) % len(eligible)
        return eligible[self._last_index]
