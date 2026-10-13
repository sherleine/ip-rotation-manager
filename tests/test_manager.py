import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.manager import ProxyManager
from app.models import ProxyState


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_request_numbers_increment_between_calls(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891, healthy=True)
        manager = ProxyManager([proxy], db_path=self.db_path)
        try:
            with patch("app.manager.get_via_proxy", return_value=(200, "ok", "mock")):
                manager.request("/")
                manager.request("/")
            self.assertEqual(manager.request_number, 2)
            self.assertEqual([event["request_id"] for event in manager.events], [1, 2])
            self.assertEqual([event["attempt"] for event in manager.events], [1, 1])
        finally:
            manager.close()

    def test_transport_failure_marks_proxy_unhealthy_and_fails_over(self):
        first = ProxyState("first", "127.0.0.1", 8891, healthy=True)
        second = ProxyState("second", "127.0.0.1", 8892, healthy=True)
        manager = ProxyManager([first, second], db_path=self.db_path)

        def request_side_effect(proxy, url):
            if proxy.name == "first":
                raise ConnectionError("simulated unavailable proxy")
            return 200, "ok", "second"

        try:
            with patch("app.manager.get_via_proxy", side_effect=request_side_effect):
                status, body = manager.request("/")
            self.assertEqual(status, 200)
            self.assertEqual(body, "ok")
            self.assertFalse(first.healthy)
            self.assertTrue(second.healthy)
            self.assertEqual(len(manager.events), 2)
            self.assertFalse(manager.events[0]["transport_ok"])
            self.assertTrue(manager.events[1]["transport_ok"])
            self.assertEqual(manager.events[0]["request_id"], manager.events[1]["request_id"])
            self.assertEqual([event["attempt"] for event in manager.events], [1, 2])
        finally:
            manager.close()

    def test_request_stops_when_no_healthy_proxies_remain(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891, healthy=False)
        manager = ProxyManager([proxy], db_path=self.db_path)
        try:
            with self.assertRaisesRegex(RuntimeError, "could not be completed"):
                manager.request("/")
            self.assertEqual(manager.request_number, 1)
            self.assertEqual(manager.events, [])
        finally:
            manager.close()

    def test_state_and_request_history_survive_manager_restart(self):
        proxy = ProxyState("mock", "127.0.0.1", 8891, healthy=True)
        first = ProxyManager([proxy], db_path=self.db_path)
        with patch("app.manager.get_via_proxy", return_value=(200, "ok", "mock")):
            first.request("/")
        first.close()

        restored_proxy = ProxyState("mock", "127.0.0.1", 8891)
        second = ProxyManager([restored_proxy], db_path=self.db_path)
        try:
            self.assertEqual(second.request_number, 1)
            self.assertTrue(restored_proxy.healthy)
            self.assertEqual(restored_proxy.total_checks, 0)
            self.assertEqual(len(second.events), 1)
        finally:
            second.close()


if __name__ == "__main__":
    unittest.main()
