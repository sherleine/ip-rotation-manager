import unittest

from app.models import ProxyState
from app.selector import NoHealthyProxyError, RoundRobinSelector


class SelectorTests(unittest.TestCase):
    def test_round_robin_cycles_healthy_proxies(self):
        proxies = [
            ProxyState("a", "127.0.0.1", 1001, healthy=True),
            ProxyState("b", "127.0.0.1", 1002, healthy=True),
            ProxyState("c", "127.0.0.1", 1003, healthy=True),
        ]
        selector = RoundRobinSelector()
        self.assertEqual(
            [selector.select(proxies).name for _ in range(6)],
            ["a", "b", "c", "a", "b", "c"],
        )

    def test_unhealthy_proxy_is_skipped(self):
        proxies = [
            ProxyState("a", "127.0.0.1", 1001, healthy=False),
            ProxyState("b", "127.0.0.1", 1002, healthy=True),
        ]
        self.assertEqual(RoundRobinSelector().select(proxies).name, "b")

    def test_disabled_proxy_is_skipped(self):
        proxies = [
            ProxyState("a", "127.0.0.1", 1001, healthy=True, disabled=True),
            ProxyState("b", "127.0.0.1", 1002, healthy=True),
        ]
        self.assertEqual(RoundRobinSelector().select(proxies).name, "b")

    def test_no_healthy_proxy_raises(self):
        with self.assertRaises(NoHealthyProxyError):
            RoundRobinSelector().select([
                ProxyState("a", "127.0.0.1", 1001, healthy=False)
            ])


if __name__ == "__main__":
    unittest.main()
