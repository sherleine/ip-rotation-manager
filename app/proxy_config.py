"""Load proxy definitions from environment variables without persisting secrets."""
import os

from app.config import HOST, PROXY_PORTS
from app.models import ProxyState


def load_proxy_definitions(environ=None):
    """Return configured proxies, defaulting to the localhost learning proxies.

    Set IPRM_PROXY_COUNT and IPRM_PROXY_1_HOST / PORT (and optional
    SCHEME / USERNAME / PASSWORD) for each numbered proxy. Credentials are
    read from the environment and are never written to the SQLite schema.
    """
    env = os.environ if environ is None else environ
    raw_count = env.get("IPRM_PROXY_COUNT")
    if raw_count is None or raw_count.strip() == "":
        return [
            ProxyState(name=f"mock-{index + 1}", host=HOST, port=port)
            for index, port in enumerate(PROXY_PORTS)
        ]

    try:
        count = int(raw_count)
    except ValueError as exc:
        raise ValueError("IPRM_PROXY_COUNT must be an integer between 1 and 20") from exc
    if not 1 <= count <= 20:
        raise ValueError("IPRM_PROXY_COUNT must be between 1 and 20")

    proxies = []
    for index in range(1, count + 1):
        prefix = f"IPRM_PROXY_{index}_"
        host = env.get(prefix + "HOST", "").strip()
        raw_port = env.get(prefix + "PORT", "").strip()
        scheme = env.get(prefix + "SCHEME", "http").strip().lower()
        username = env.get(prefix + "USERNAME", "")
        password = env.get(prefix + "PASSWORD", "")

        if not host:
            raise ValueError(f"{prefix}HOST is required")
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError(f"{prefix}PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"{prefix}PORT must be between 1 and 65535")
        if scheme not in ("http", "https"):
            raise ValueError(f"{prefix}SCHEME must be http or https")
        if bool(username) != bool(password):
            raise ValueError(
                f"{prefix}USERNAME and {prefix}PASSWORD must both be set, or both omitted"
            )

        proxies.append(ProxyState(
            name=f"proxy-{index}",
            host=host,
            port=port,
            scheme=scheme,
            username=username or None,
            password=password or None,
        ))
    return proxies


def masked_proxy_url(proxy):
    """Render a proxy endpoint without exposing its credentials."""
    host = f"[{proxy.host}]" if ":" in proxy.host and not proxy.host.startswith("[") else proxy.host
    return f"{proxy.scheme}://{host}:{proxy.port}"
