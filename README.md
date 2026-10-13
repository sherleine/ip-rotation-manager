# IP Rotation Manager

A Python CLI project for learning proxy selection, health monitoring, failover, and request logging in a controlled localhost lab.

## MVP scope

- Local mock HTTP target and three mock proxy endpoints.
- Health-aware round-robin selection and bounded failover.
- SQLite persistence for proxy health state and request-attempt history.
- Recovery cooldown: a proxy with repeated failures is temporarily excluded from health checks and requests, then rechecked after the cooldown expires.
- CLI commands to inspect saved status, run active health checks, review recent request attempts, and validate proxy configuration.
- Unit tests for selection, health state, persistence, transport failover, and cooldown recovery.
- A `demo-failover` command that simulates a mock proxy dropping connections and demonstrates automatic failover.
- Python standard library only; no pip packages required.

> Safety note: This is a learning lab. Mock proxies do not change your public IP address. Use the included localhost target until you configure an authorized proxy provider and approved destination. Do not use the project to evade access controls or rate limits.

## Requirements

- Windows 10/11
- Python 3.11+ (tested by the user on Python 3.13)
- VS Code optional

## Run on Windows PowerShell

```powershell
# Run the regular local demo (checks proxies and sends six requests)
py -m app.main demo

# Simulate one mock proxy failing and observe failover
py -m app.main demo-failover

# Display last saved proxy health, latency, failure count, and cooldown
py -m app.main status

# Start the localhost lab and actively check proxy health
py -m app.main health-check

# Show the latest saved request attempts
py -m app.main history

# Validate proxy configuration (does not connect to proxies)
py -m app.main config-check

# Run all tests
py -m unittest discover -s tests -v
```

### Environment-based proxy configuration

The new `config-check` command validates proxy settings without connecting to them. By default, it displays the three localhost mock proxies.

To define one proxy in the current PowerShell session, set environment variables like these:

```powershell
$env:IPRM_PROXY_COUNT = "1"
$env:IPRM_PROXY_1_HOST = "proxy.example.com"
$env:IPRM_PROXY_1_PORT = "8080"
$env:IPRM_PROXY_1_SCHEME = "http"
$env:IPRM_PROXY_1_USERNAME = "your-username"
$env:IPRM_PROXY_1_PASSWORD = "your-password"
py -m app.main config-check
```

Use the actual host, port, and credentials supplied by a proxy provider you are authorized to use. Add more endpoints by setting `IPRM_PROXY_COUNT` and the matching numbered variables. Credentials are masked by `config-check` and are not added to the SQLite proxy-state table. Environment variables set this way last only for the current PowerShell session; do not commit credentials to Git.

**Important:** this stage only prepares and validates configuration. The existing `demo`, `health-check`, and request routing commands still use the localhost lab. Provider connectivity and real exit-IP verification are separate future work.

### What the new commands mean

- `status` displays the **last saved result**. It does not contact the proxies, so use `health-check` to test them now.
- `health-check` starts the local test lab, checks the mock proxies, saves results, and then stops the lab.
- `history` displays recent request attempts saved in SQLite. It may be empty until you run `demo`.

The default SQLite database is created at `data/proxy_manager.sqlite3`. It is safe to remove this file when you want to reset the demo's saved history. Do not delete it while the application is running.

## Recovery behavior

- Consecutive failures are counted.
- Once the configured threshold is reached, the endpoint receives a 30-second cooldown.
- During cooldown, requests do not use the endpoint and health checks do not repeatedly hit it.
- After cooldown expires, the next health refresh checks the endpoint again; a successful check clears its failure count and cooldown.
- Values can be changed in `app/config.py`.

## Project structure

```text
app/
  config.py
  database.py
  health_checker.py
  local_lab.py
  main.py
  manager.py
  models.py
  request_client.py
  selector.py
tests/
  test_database.py
  test_local_lab.py
  test_manager.py
  test_models.py
  test_selector.py
```

## Current limitations

- The mock proxies only forward to the local test target.
- HTTPS CONNECT is intentionally unsupported in this MVP.
- Third-party provider integration is not yet implemented.
