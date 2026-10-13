"""Data models for proxy endpoints and their observed health."""
from dataclasses import dataclass
from time import time
from typing import Optional
from urllib.parse import quote


@dataclass
class ProxyState:
    name: str
    host: str
    port: int
    healthy: bool = False
    latency_ms: Optional[float] = None
    consecutive_failures: int = 0
    total_checks: int = 0
    successful_checks: int = 0
    last_checked_at: Optional[float] = None
    last_error: Optional[str] = None
    disabled: bool = False
    cooldown_until: Optional[float] = None
    scheme: str = "http"
    username: Optional[str] = None
    password: Optional[str] = None

    @property
    def url(self) -> str:
        """Return the proxy URL, percent-encoding optional credentials."""
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        credentials = ""
        if self.username is not None and self.password is not None:
            credentials = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}@"
        return f"{self.scheme}://{credentials}{host}:{self.port}"

    @property
    def success_rate(self) -> float:
        if not self.total_checks:
            return 0.0
        return self.successful_checks / self.total_checks * 100.0

    def in_cooldown(self, now: Optional[float] = None) -> bool:
        """Return whether this proxy should wait before another health check."""
        return self.cooldown_until is not None and (time() if now is None else now) < self.cooldown_until

    def record_check(
        self,
        success: bool,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None,
        cooldown_seconds: float = 0.0,
        cooldown_threshold: int = 1,
    ) -> None:
        self.total_checks += 1
        self.last_checked_at = time()
        self.last_error = error
        if success:
            self.successful_checks += 1
            self.consecutive_failures = 0
            self.healthy = True
            self.latency_ms = latency_ms
            self.cooldown_until = None
        else:
            self.consecutive_failures += 1
            self.healthy = False
            if cooldown_seconds > 0 and self.consecutive_failures >= cooldown_threshold:
                self.cooldown_until = time() + cooldown_seconds
