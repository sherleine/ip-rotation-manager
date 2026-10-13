import tempfile
import unittest
from pathlib import Path

from app.database import ProxyDatabase
from app.models import ProxyState


class ProxyDatabaseTests(unittest.TestCase):
    def test_proxy_state_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ProxyDatabase(str(Path(folder) / "state.sqlite3"))
            proxy = ProxyState(
                "mock-1", "127.0.0.1", 8891, healthy=True,
                latency_ms=4.2, total_checks=3, successful_checks=2,
                consecutive_failures=1, cooldown_until=1234.0,
            )
            database.save_proxy(proxy)
            row = database.load_proxy_states()["mock-1"]
            self.assertEqual(row["healthy"], 1)
            self.assertEqual(row["total_checks"], 3)
            self.assertEqual(row["cooldown_until"], 1234.0)
            database.close()

    def test_request_events_round_trip_and_increment_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            database = ProxyDatabase(str(Path(folder) / "state.sqlite3"))
            database.save_event({
                "request_id": 7, "attempt": 1, "proxy": "mock-1",
                "status": 200, "transport_ok": True, "proxy_header": "mock-1",
            })
            self.assertEqual(database.next_request_id(), 7)
            self.assertEqual(database.load_events()[0]["request_id"], 7)
            database.close()


if __name__ == "__main__":
    unittest.main()
