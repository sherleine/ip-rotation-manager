"""Configuration for the localhost-only learning lab."""
HOST = "127.0.0.1"
# A non-local hostname ensures urllib sends these requests through the configured proxy.
TARGET_HOSTNAME = "rotation-target.invalid"
TARGET_PORT = 8765
PROXY_PORTS = (8891, 8892, 8893)
HEALTH_PATH = "/health"
HEALTH_TIMEOUT_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 2.0
MAX_CONSECUTIVE_FAILURES = 2
MAX_RETRIES_PER_REQUEST = 3
RECOVERY_COOLDOWN_SECONDS = 30
DATABASE_PATH = "data/proxy_manager.sqlite3"

# Web Data API smoke test (py -m app.main webdata-test): one real page, and a
# string that only appears when real listing content came back.
WEBDATA_TEST_URL = "https://clutch.co/developers/artificial-intelligence"
WEBDATA_EXPECT_TEXT = "provider-list-item"
