import unittest

from app.proxy_config import load_proxy_definitions, masked_proxy_url


class ProxyConfigTests(unittest.TestCase):
    def test_defaults_to_local_mock_proxies(self):
        proxies = load_proxy_definitions({})
        self.assertEqual([proxy.name for proxy in proxies], ["mock-1", "mock-2", "mock-3"])
        self.assertEqual([proxy.port for proxy in proxies], [8891, 8892, 8893])

    def test_loads_environment_proxy_and_credentials(self):
        proxies = load_proxy_definitions({
            "IPRM_PROXY_COUNT": "1",
            "IPRM_PROXY_1_HOST": "proxy.example.test",
            "IPRM_PROXY_1_PORT": "8080",
            "IPRM_PROXY_1_USERNAME": "user name",
            "IPRM_PROXY_1_PASSWORD": "p@ss:/word",
        })
        self.assertEqual(len(proxies), 1)
        self.assertEqual(proxies[0].username, "user name")
        self.assertEqual(proxies[0].password, "p@ss:/word")
        self.assertEqual(
            proxies[0].url,
            "http://user%20name:p%40ss%3A/word@proxy.example.test:8080",
        )
        self.assertEqual(masked_proxy_url(proxies[0]), "http://proxy.example.test:8080")

    def test_rejects_missing_host(self):
        with self.assertRaisesRegex(ValueError, "HOST is required"):
            load_proxy_definitions({
                "IPRM_PROXY_COUNT": "1",
                "IPRM_PROXY_1_PORT": "8080",
            })

    def test_rejects_partial_credentials(self):
        with self.assertRaisesRegex(ValueError, "must both be set"):
            load_proxy_definitions({
                "IPRM_PROXY_COUNT": "1",
                "IPRM_PROXY_1_HOST": "proxy.example.test",
                "IPRM_PROXY_1_PORT": "8080",
                "IPRM_PROXY_1_USERNAME": "user",
            })

    def test_rejects_invalid_port(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            load_proxy_definitions({
                "IPRM_PROXY_COUNT": "1",
                "IPRM_PROXY_1_HOST": "proxy.example.test",
                "IPRM_PROXY_1_PORT": "70000",
            })


if __name__ == "__main__":
    unittest.main()
