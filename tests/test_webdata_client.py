import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import webdata_client
from app.webdata_client import (
    AccessBlockedError,
    RobotsDisallowedError,
    WebDataError,
    fetch_html,
    is_block_page,
    load_env_file,
    parse_robots,
    robots_allows,
)

ROBOTS = """
User-agent: SomeBot
Disallow: /

User-agent: *
Disallow: /lp/
Disallow: /*?*hourly_rate=*
Allow: /lp/public$

Sitemap: https://clutch.co/sitemap.xml
"""
LISTING = "https://clutch.co/developers/artificial-intelligence"


class RobotsTests(unittest.TestCase):
    def setUp(self):
        self.rules = parse_robots(ROBOTS)

    def test_other_agent_groups_are_ignored(self):
        self.assertNotIn((False, "/"), self.rules)

    def test_unfiltered_listing_and_pages_allowed(self):
        self.assertTrue(robots_allows(self.rules, LISTING))
        self.assertTrue(robots_allows(self.rules, LISTING + "?page=3"))

    def test_wildcard_query_rule_blocks_filter(self):
        self.assertFalse(robots_allows(self.rules, LISTING + "?hourly_rate=50-99"))
        self.assertFalse(robots_allows(self.rules, LISTING + "?page=2&hourly_rate=300"))

    def test_longest_match_and_end_anchor(self):
        self.assertFalse(robots_allows(self.rules, "https://clutch.co/lp/offer"))
        self.assertTrue(robots_allows(self.rules, "https://clutch.co/lp/public"))
        self.assertFalse(robots_allows(self.rules, "https://clutch.co/lp/public/more"))


class BlockDetectionTests(unittest.TestCase):
    def test_status_codes_and_markers(self):
        self.assertTrue(is_block_page(403, "<html></html>"))
        self.assertTrue(is_block_page(200, "<title>Just a moment...</title>"))
        self.assertFalse(is_block_page(200, "<title>Top Artificial Intelligence Companies</title>"))


class FetchTests(unittest.TestCase):
    def setUp(self):
        webdata_client._robots_cache.clear()
        webdata_client._robots_cache["https://clutch.co"] = parse_robots(ROBOTS)

    def tearDown(self):
        webdata_client._robots_cache.clear()

    def test_disallowed_url_is_refused_before_any_api_call(self):
        with mock.patch.object(webdata_client, "_scrape") as scrape:
            with self.assertRaises(RobotsDisallowedError):
                fetch_html(LISTING + "?hourly_rate=50-99")
            scrape.assert_not_called()

    def test_robots_check_can_be_skipped_for_a_chosen_url(self):
        with mock.patch.object(webdata_client, "_scrape", return_value=(200, "<html>ok</html>")),                 mock.patch.object(webdata_client, "_robots_rules") as rules:
            self.assertEqual(fetch_html(LISTING + "?hourly_rate=50-99", respect_robots=False), "<html>ok</html>")
            rules.assert_not_called()

    def test_skipping_robots_still_stops_on_a_challenge(self):
        with mock.patch.object(webdata_client, "_scrape", return_value=(200, "<title>Just a moment...</title>")):
            with self.assertRaises(AccessBlockedError):
                fetch_html(LISTING + "?hourly_rate=50-99", respect_robots=False)

    def test_challenge_page_stops(self):
        with mock.patch.object(webdata_client, "_scrape", return_value=(200, "<title>Just a moment...</title>")):
            with self.assertRaises(AccessBlockedError):
                fetch_html(LISTING)

    def test_site_error_is_reported(self):
        with mock.patch.object(webdata_client, "_scrape", return_value=(404, "<html>missing</html>")):
            with self.assertRaises(WebDataError):
                fetch_html(LISTING)

    def test_real_page_is_returned(self):
        with mock.patch.object(webdata_client, "_scrape", return_value=(200, "<html>ok</html>")):
            self.assertEqual(fetch_html(LISTING), "<html>ok</html>")


class RetryTests(unittest.TestCase):
    def test_dropped_connection_is_retried(self):
        flaky = [WebDataError("reset", retryable=True), (200, "<html>ok</html>")]

        def once(url):
            item = flaky.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(webdata_client, "_scrape_once", side_effect=once),                 mock.patch.object(webdata_client.time, "sleep") as sleep:
            self.assertEqual(webdata_client._scrape(LISTING), (200, "<html>ok</html>"))
            sleep.assert_called_once_with(webdata_client.RETRY_DELAYS_SECONDS[0])

    def test_bad_key_is_not_retried(self):
        with mock.patch.object(webdata_client, "_scrape_once", side_effect=WebDataError("401")) as once,                 mock.patch.object(webdata_client.time, "sleep"):
            with self.assertRaises(WebDataError):
                webdata_client._scrape(LISTING)
            self.assertEqual(once.call_count, 1)

    def test_gives_up_after_the_last_retry(self):
        with mock.patch.object(webdata_client, "_scrape_once", side_effect=WebDataError("x", retryable=True)) as once,                 mock.patch.object(webdata_client.time, "sleep"):
            with self.assertRaises(WebDataError):
                webdata_client._scrape(LISTING)
            self.assertEqual(once.call_count, len(webdata_client.RETRY_DELAYS_SECONDS) + 1)

    def test_connection_reset_becomes_a_retryable_error(self):
        with mock.patch.object(webdata_client, "_api_settings", return_value=("https://api.test", "Bearer k")),                 mock.patch.object(webdata_client, "urlopen", side_effect=ConnectionResetError(10054, "reset")):
            with self.assertRaises(WebDataError) as caught:
                webdata_client._scrape_once(LISTING)
        self.assertTrue(caught.exception.retryable)


class EnvFileTests(unittest.TestCase):
    def test_loads_values_without_overriding_real_env(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("# comment\nIPRM_T_A=from-file\nIPRM_T_B='quoted'\nIPRM_T_EMPTY=\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"IPRM_T_A": "real"}, clear=False):
                load_env_file(path)
                self.assertEqual(os.environ["IPRM_T_A"], "real")
                self.assertEqual(os.environ["IPRM_T_B"], "quoted")
                self.assertNotIn("IPRM_T_EMPTY", os.environ)

    def test_api_key_uses_bearer_and_data_api(self):
        with mock.patch.dict(os.environ, {"WEBDATA_API_KEY": "a" * 64, "WEBDATA_API_URL": ""}), \
                mock.patch.object(webdata_client, "load_env_file"):
            url, auth = webdata_client._api_settings()
        self.assertEqual(url, webdata_client.API_KEY_URL)
        self.assertEqual(auth, "Bearer " + "a" * 64)

    def test_basic_token_uses_scraper_api(self):
        token = base64.b64encode(b"user:pass").decode()
        for value in (token, "Basic " + token):
            with mock.patch.dict(os.environ, {"WEBDATA_API_KEY": value, "WEBDATA_API_URL": ""}), \
                    mock.patch.object(webdata_client, "load_env_file"):
                url, auth = webdata_client._api_settings()
            self.assertEqual(url, webdata_client.BASIC_TOKEN_URL)
            self.assertEqual(auth, "Basic " + token)

    def test_missing_key_is_a_clear_error(self):
        with mock.patch.dict(os.environ, {"WEBDATA_API_KEY": ""}), \
                mock.patch.object(webdata_client, "load_env_file"):
            with self.assertRaises(WebDataError):
                webdata_client._api_settings()


if __name__ == "__main__":
    unittest.main()
