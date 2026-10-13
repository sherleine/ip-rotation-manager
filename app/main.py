"""CLI entry point."""
import argparse
import tempfile
import time
from pathlib import Path

from app.config import HOST, PROXY_PORTS
from app.local_lab import start_lab, stop_lab, set_mock_proxy_available
from app.manager import ProxyManager
from app.models import ProxyState


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


def main():
    parser = argparse.ArgumentParser(
        description="Local IP rotation/proxy-management learning MVP"
    )
    parser.add_argument(
        "command", choices=["demo", "demo-failover"],
        help="Run the localhost demo or a simulated proxy failure/failover demo",
    )
    args = parser.parse_args()
    if args.command == "demo":
        run_demo()
    elif args.command == "demo-failover":
        run_failover_demo()


if __name__ == "__main__":
    main()
