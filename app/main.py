"""CLI entry point."""
import argparse
import time

from app.config import HOST, PROXY_PORTS
from app.local_lab import start_lab, stop_lab
from app.manager import ProxyManager
from app.models import ProxyState


def run_demo():
    print("IP Rotation Manager — localhost demo")
    print("Only the included local test target is permitted by mock proxies.")
    servers = start_lab()
    manager = None
    try:
        time.sleep(0.2)
        proxies = [
            ProxyState(name=f"mock-{index + 1}", host=HOST, port=port)
            for index, port in enumerate(PROXY_PORTS)
        ]
        manager = ProxyManager(proxies)
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


def main():
    parser = argparse.ArgumentParser(
        description="Local IP rotation/proxy-management learning MVP"
    )
    parser.add_argument(
        "command", choices=["demo"],
        help="Run the localhost-only demonstration",
    )
    args = parser.parse_args()
    if args.command == "demo":
        run_demo()


if __name__ == "__main__":
    main()
