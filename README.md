# IP Rotation Manager

A Python CLI project for learning proxy selection, health monitoring, failover, and request logging in a controlled localhost lab.

## MVP scope

- Local mock HTTP target and proxy endpoints.
- Health-aware round-robin selection.
- Basic proxy health checks and request logs.
- Unit tests for proxy selection.
- No paid proxy provider or external scraping target required.

> This initial version is a learning lab. The mock proxies do not change your public IP address. Test with local endpoints and only use proxy services and destinations you are authorized to access.

## Requirements

- Windows 10/11
- Python 3.11+ (tested with Python 3.13)
- VS Code optional

## Run

```powershell
py -m app.main demo
py -m unittest discover -s tests -v
```

## Planned milestones

1. Core models and health-aware round-robin selection.
2. Local-only mock proxy lab and bounded retry/failover.
3. Recovery tests for temporarily unavailable proxies.
4. SQLite persistence and reporting.
5. Provider adapter for authorized proxy services.
