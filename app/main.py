"""CLI entry point."""
import argparse
import tempfile
import time
from pathlib import Path

from app.config import HOST, PROXY_PORTS
from app.local_lab import start_lab, stop_lab, set_mock_proxy_available
from app.manager import ProxyManager
from app.models import ProxyState
from app.proxy_config import load_proxy_definitions, masked_proxy_url


def _make_proxies():
    return [
        ProxyState(name=f"mock-{index + 1}", host=HOST, port=port)
        for index, port in enumerate(PROXY_PORTS)
    ]


def run_demo():
    print("IP Rotation Manager — localhost demo")
    print("Only the included local test target is permitted by mock proxies.")
    servers = start_lab()
    manager = None
    try:
        time.sleep(0.2)
        manager = ProxyManager(_make_proxies())
        manager.refresh_health()
        print("Sending 6 requests through the selector...")
        for _ in range(6):
            _status, body = manager.request("/")
            print(f"  Response body: {body[:100]}")
        manager.print_summary()
        print("\nSQLite database: data/proxy_manager.sqlite3")
    finally:
        if manager is not None:
            manager.close()
        stop_lab(servers)
        print("\nLocal lab stopped.")


def run_failover_demo():
    print("IP Rotation Manager — simulated proxy failure demo")
    print("Local-only test: mock-1 will drop connections; no external sites are contacted.")
    servers = start_lab()
    manager = None
    # Keep this demonstration isolated from the normal demo's saved history/state.
    with tempfile.TemporaryDirectory(prefix="ip-rotation-failover-") as folder:
        try:
            time.sleep(0.2)
            manager = ProxyManager(_make_proxies(), db_path=str(Path(folder) / "demo.sqlite3"))
            manager.refresh_health()
            print("\nSimulating mock-1 going offline...")
            set_mock_proxy_available("mock-1", False)
            status, body = manager.request("/")
            print(f"\nRequest completed through failover: HTTP {status}; body={body[:100]}")
            manager.print_summary()
            set_mock_proxy_available("mock-1", True)
            print("\nmock-1 is back online in the lab. Run health-check logic after cooldown to verify recovery.")
        finally:
            set_mock_proxy_available("mock-1", True)
            if manager is not None:
                manager.close()
            stop_lab(servers)
            print("\nLocal lab stopped.")


def _status_label(proxy):
    if proxy.disabled:
        return "DISABLED"
    if proxy.in_cooldown():
        return "COOLDOWN"
    return "HEALTHY" if proxy.healthy else "UNHEALTHY"


def run_status():
    """Show saved status without making live network checks."""
    manager = ProxyManager(_make_proxies())
    try:
        print("Proxy status (last saved result; run 'health-check' to test now)")
        print("-" * 88)
        print(f"{'Proxy':10} {'Status':12} {'Latency':12} {'Failures':>9} {'Cooldown':>10}  Last error")
        for proxy in manager.proxies:
            if proxy.cooldown_until is not None and proxy.in_cooldown():
                remaining = f"{max(0, int(proxy.cooldown_until - time.time()))}s"
            else:
                remaining = "-"
            latency = f"{proxy.latency_ms:.1f} ms" if proxy.latency_ms is not None else "n/a"
            error = (proxy.last_error or "-").replace("\n", " ")
            if len(error) > 35:
                error = error[:32] + "..."
            print(
                f"{proxy.name:10} {_status_label(proxy):12} {latency:12} "
                f"{proxy.consecutive_failures:9} {remaining:>10}  {error}"
            )
    finally:
        manager.close()


def run_health_check():
    """Start the localhost lab and actively check every eligible mock proxy."""
    print("Running active health checks against the localhost mock proxies.")
    servers = start_lab()
    manager = None
    try:
        time.sleep(0.2)
        manager = ProxyManager(_make_proxies())
        manager.refresh_health()
        manager.print_summary()
    finally:
        if manager is not None:
            manager.close()
        stop_lab(servers)
        print("Local lab stopped.")


def run_history(limit=20):
    """Display the most recent saved request attempts."""
    manager = ProxyManager(_make_proxies())
    try:
        events = manager.events[-limit:]
        print(f"Recent request attempts (showing {len(events)}; newest at bottom)")
        if not events:
            print("No request history found. Run 'demo' to create some history.")
            return
        print("-" * 88)
        for event in events:
            request_id = event.get("request_id", "?")
            attempt = event.get("attempt", "?")
            proxy = event.get("proxy", "unknown")
            if event.get("transport_ok"):
                result = f"HTTP {event.get('status', 'unknown')}"
                detail = f"header={event.get('proxy_header') or 'not supplied'}"
            else:
                result = "FAILED"
                detail = event.get("error") or "transport error"
            print(f"Request {request_id:<5} attempt {attempt:<2} {proxy:10} {result:10} {detail}")
    finally:
        manager.close()


def run_config_check():
    """Validate environment proxy settings without contacting any endpoint."""
    try:
        proxies = load_proxy_definitions()
    except ValueError as exc:
        raise SystemExit(f"Invalid proxy configuration: {exc}") from exc

    using_local_defaults = "IPRM_PROXY_COUNT" not in __import__("os").environ
    mode = "local mock defaults" if using_local_defaults else "environment configuration"
    print(f"Proxy configuration is valid ({mode}).")
    print("Credentials are configured only in environment variables and are not displayed.")
    for proxy in proxies:
        print(f"  {proxy.name:10} {masked_proxy_url(proxy)}")
    print("\nThis command validates configuration only; it does not connect to proxies.")


def main():
    parser = argparse.ArgumentParser(
        description="Local IP rotation/proxy-management learning MVP"
    )
    parser.add_argument(
        "command",
        choices=["demo", "demo-failover", "status", "health-check", "history", "config-check"],
        help="Run a demo, inspect saved status/history, or actively check local mock proxies",
    )
    args = parser.parse_args()
    if args.command == "demo":
        run_demo()
    elif args.command == "demo-failover":
        run_failover_demo()
    elif args.command == "status":
        run_status()
    elif args.command == "health-check":
        run_health_check()
    elif args.command == "history":
        run_history()
    elif args.command == "config-check":
        run_config_check()


if __name__ == "__main__":
    main()
