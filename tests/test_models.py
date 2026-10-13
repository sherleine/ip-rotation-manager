import unittest

from app.models import ProxyState


class ProxyStateTests(unittest.TestCase):
    def test_success_updates_health_and_resets_failures(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891, consecutive_failures=2)
        proxy.record_check(True, latency_ms=12.5)
        self.assertTrue(proxy.healthy)
        self.assertEqual(proxy.consecutive_failures, 0)
        self.assertEqual(proxy.latency_ms, 12.5)
        self.assertEqual(proxy.success_rate, 100.0)

    def test_failure_marks_proxy_unhealthy(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891, healthy=True)
        proxy.record_check(False, error="connection refused")
        self.assertFalse(proxy.healthy)
        self.assertEqual(proxy.consecutive_failures, 1)
        self.assertEqual(proxy.success_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
