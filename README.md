# IP Rotation Manager

A Python CLI project for learning proxy selection, health monitoring, failover, and request logging in a controlled localhost lab.

## MVP scope

- Local mock HTTP target and three mock proxy endpoints.
- Health-aware round-robin selection and bounded failover.
- SQLite persistence for proxy health state and request-attempt history.
- Recovery cooldown: a proxy with repeated failures is temporarily excluded from health checks and requests, then rechecked after the cooldown expires.
- Unit tests for selection, health state, persistence, and failover.
- Python standard library only; no pip packages required.

> Safety note: This is a learning lab. Mock proxies do not change your public IP address. Use the included localhost target until you configure an authorized proxy provider and approved destination. Do not use the project to evade access controls or rate limits.

## Requirements

- Windows 10/11
- Python 3.11+ (tested by the user on Python 3.13)
- VS Code optional

## Run on Windows PowerShell

```powershell
py -m app.main demo
py -m unittest discover -s tests -v
```

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
  test_manager.py
  test_models.py
  test_selector.py
```

## Current limitations

- The mock proxies only forward to the local test target.
- HTTPS CONNECT is intentionally unsupported in this MVP.
- Third-party provider integration is not yet implemented.
