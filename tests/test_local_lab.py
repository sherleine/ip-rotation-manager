import tempfile
import time
import unittest
from pathlib import Path

from app.config import HOST, PROXY_PORTS
from app.health_checker import check_proxy
from app.local_lab import start_lab, stop_lab, set_mock_proxy_available
from app.manager import ProxyManager
from app.models import ProxyState


class LocalLabFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.servers = start_lab()
        time.sleep(0.15)
        proxies = [
            ProxyState(name=f"mock-{index + 1}", host=HOST, port=port)
            for index, port in enumerate(PROXY_PORTS)
        ]
        self.manager = ProxyManager(
            proxies, db_path=str(Path(self.temp_dir.name) / "test.sqlite3")
        )
        self.manager.refresh_health()

    def tearDown(self):
        set_mock_proxy_available("mock-1", True)
        self.manager.close()
        stop_lab(self.servers)
        self.temp_dir.cleanup()

    def test_offline_mock_proxy_fails_over_to_healthy_proxy(self):
        set_mock_proxy_available("mock-1", False)

        status, body = self.manager.request("/")

        self.assertEqual(status, 200)
        self.assertIn("local-test-target", body)
        self.assertEqual(len(self.manager.events), 2)
        self.assertEqual(self.manager.events[0]["proxy"], "mock-1")
        self.assertFalse(self.manager.events[0]["transport_ok"])
        self.assertEqual(self.manager.events[1]["proxy"], "mock-2")
        self.assertTrue(self.manager.events[1]["transport_ok"])
        self.assertFalse(self.manager.proxies[0].healthy)
        self.assertTrue(self.manager.proxies[1].healthy)

    def test_proxy_recovers_after_cooldown_expires(self):
        proxy = self.manager.proxies[0]
        set_mock_proxy_available("mock-1", False)

        self.assertFalse(check_proxy(proxy))
        self.assertFalse(check_proxy(proxy))
        self.assertTrue(proxy.in_cooldown())
        self.assertFalse(proxy.healthy)

        set_mock_proxy_available("mock-1", True)
        self.manager.refresh_health()
        self.assertTrue(proxy.in_cooldown())
        self.assertFalse(proxy.healthy)

        # Avoid sleeping 30 seconds in a unit test; simulate the cooldown expiring.
        proxy.cooldown_until = time.time() - 1
        self.manager.refresh_health()

        self.assertTrue(proxy.healthy)
        self.assertFalse(proxy.in_cooldown())
        self.assertEqual(proxy.consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
