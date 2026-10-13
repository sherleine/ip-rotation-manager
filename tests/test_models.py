import unittest
from time import time

from app.models import ProxyState


class ProxyStateTests(unittest.TestCase):
    def test_success_updates_health_and_resets_failures(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891, consecutive_failures=2)
        proxy.record_check(True, latency_ms=12.5)
        self.assertTrue(proxy.healthy)
        self.assertEqual(proxy.consecutive_failures, 0)
        self.assertEqual(proxy.latency_ms, 12.5)
        self.assertEqual(proxy.success_rate, 100.0)
        self.assertIsNone(proxy.cooldown_until)

    def test_failure_marks_proxy_unhealthy(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891, healthy=True)
        proxy.record_check(False, error="connection refused")
        self.assertFalse(proxy.healthy)
        self.assertEqual(proxy.consecutive_failures, 1)
        self.assertEqual(proxy.success_rate, 0.0)

    def test_cooldown_activates_at_failure_threshold(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891)
        proxy.record_check(False, cooldown_seconds=30, cooldown_threshold=2)
        self.assertIsNone(proxy.cooldown_until)
        proxy.record_check(False, cooldown_seconds=30, cooldown_threshold=2)
        self.assertTrue(proxy.in_cooldown())
        self.assertGreater(proxy.cooldown_until, time())

    def test_expired_cooldown_allows_health_check(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891, cooldown_until=time() - 1)
        self.assertFalse(proxy.in_cooldown())


if __name__ == "__main__":
    unittest.main()