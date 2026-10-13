"""Data models for proxy endpoints and their observed health."""
from dataclasses import dataclass
from time import time
from typing import Optional


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

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        if not self.total_checks:
            return 0.0
        return self.successful_checks / self.total_checks * 100.0

    def record_check(
        self,
        success: bool,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        self.total_checks += 1
        self.last_checked_at = time()
        self.last_error = error
        if success:
            self.successful_checks += 1
            self.consecutive_failures = 0
            self.healthy = True
            self.latency_ms = latency_ms
        else:
            self.consecutive_failures += 1
            self.healthy = False
