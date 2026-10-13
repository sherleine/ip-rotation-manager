# IP Rotation Manager

A Python CLI project for learning proxy selection, health monitoring, failover, and request logging in a controlled localhost lab.

## MVP scope

- Local mock HTTP target and three mock proxy endpoints.
- Health-aware round-robin selection.
- Proxy health checks and request event logging.
- Bounded per-request failover attempts.
- Unit tests for proxy selection and health-state model behavior.
- No paid proxy provider or external scraping target required.

> Safety note: This is a learning lab. Mock proxies do not change your public IP address. Use the included localhost target until you configure an authorized proxy provider and approved destination. Do not use the project to evade access controls or rate limits.

## Requirements

- Windows 10/11
- Python 3.11+ (the user-tested environment is Python 3.13)
- VS Code optional
- Python standard library only; no pip packages required

## Run on Windows PowerShell

```powershell
py -m app.main demo
py -m unittest discover -s tests -v
```

## Project structure

```text
app/
  config.py
  health_checker.py
  local_lab.py
  main.py
  manager.py
  models.py
  request_client.py
  selector.py
tests/
  test_models.py
  test_selector.py
```

## Current limitations

- The mock proxies only forward to the local test target.
- HTTPS CONNECT is intentionally unsupported in this MVP.
- Health checks are simple request-response checks; cooldown-based recovery and persistent SQLite metrics are planned next.
- Third-party provider integration is not yet implemented.

## Roadmap

1. Core models and health-aware selection.
2. Local mock proxy lab and bounded failover.
3. Simulated endpoint failure and recovery tests.
4. SQLite persistence and performance reports.
5. Provider adapter for authorized proxy services.
