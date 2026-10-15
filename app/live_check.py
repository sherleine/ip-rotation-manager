"""Phase 1 live connectivity check for a residential gateway provider.

Sends a few requests through the real gateway to an IP-echo endpoint and
prints the exit IP, country, and ISP for each:

    - two rotating requests  -> expect two different IPs
    - two sticky requests    -> expect the same IP twice
    - one geo-targeted request (if --geo is given) -> expect that country

Credentials come from env vars (<PREFIX>_HOST, _PORT, _USER, _PASS); the
password is never printed. Each request costs a few KB of bandwidth.

    py -m app.live_check                    # uses DECODO_* env vars
    py -m app.live_check --geo us
    py -m app.live_check --prefix OXYLABS
"""
import argparse
import json
import sys
import uuid
from urllib.parse import unquote, urlsplit
from urllib.request import ProxyHandler, build_opener

from app.providers import GatewayConfig, ProxyEndpoint, ResidentialGatewayProvider

ECHO_URL = "https://ipinfo.io/json"  # returns ip, country, org (ISP)
TIMEOUT_SECONDS = 20


def fetch_exit_info(endpoint: ProxyEndpoint) -> dict:
    opener = build_opener(ProxyHandler(endpoint.as_proxies()))
    with opener.open(ECHO_URL, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def describe(label: str, endpoint: ProxyEndpoint) -> str | None:
    username = unquote(urlsplit(endpoint.url).username or "")
    try:
        info = fetch_exit_info(endpoint)
    except Exception as exc:  # report and keep going so every mode gets tried
        print(f"  {label:<10} user={username}  FAILED: {exc}")
        return None
    print(f"  {label:<10} ip={info.get('ip'):<16} country={info.get('country')}  "
          f"org={info.get('org')}  user={username}")
    return info.get("ip")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 live gateway check")
    parser.add_argument("--prefix", default="DECODO", help="env var prefix (default DECODO)")
    parser.add_argument("--geo", help="country code for the geo-targeted check, e.g. us")
    args = parser.parse_args()

    try:
        config = GatewayConfig.from_env(args.prefix)
    except ValueError as exc:
        print(f"Config error: {exc}")
        return 2

    provider = ResidentialGatewayProvider(config)
    print(f"Provider {config.name} via {config.gateway_host}:{config.gateway_port}\n")

    rot1 = describe("rotating", provider.endpoint())
    rot2 = describe("rotating", provider.endpoint())

    session_id = uuid.uuid4().hex[:12]
    sticky1 = describe("sticky", provider.endpoint(session_id=session_id))
    sticky2 = describe("sticky", provider.endpoint(session_id=session_id))

    if args.geo:
        describe(f"geo={args.geo}", provider.endpoint(geo=args.geo))

    print()
    ok = True
    if rot1 and rot2:
        rotated = rot1 != rot2
        ok &= rotated
        print(f"Rotating gave different IPs: {'yes' if rotated else 'NO'}")
    else:
        ok = False
    if sticky1 and sticky2:
        held = sticky1 == sticky2
        ok &= held
        print(f"Sticky held the same IP:     {'yes' if held else 'NO'}")
    else:
        ok = False
    print("\nPhase 1 check " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
