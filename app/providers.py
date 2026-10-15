"""Proxy provider abstraction for the rotation service.

The key idea for RAW RESIDENTIAL/MOBILE proxies: the provider does NOT give you
a list of IPs. It gives you ONE gateway endpoint plus credentials, and you pick
an exit IP by encoding parameters into the *username*:

    - rotating  (new IP per connection):  acct
    - sticky    (hold one IP):            acct-session-<id>
    - geo       (country target):         acct-country-us
    - combined:                           acct-country-us-session-<id>

The exact username syntax differs per provider, so each provider is a small
adapter that knows how to build its own username from a common request. The
rest of the system only ever talks to the ProxyProvider interface.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote


@dataclass(frozen=True)
class ProxyEndpoint:
    """A ready-to-use proxy URL plus the context it was built for."""
    url: str                     # http://user-...:pass@gate.provider.com:7000
    provider: str
    geo: Optional[str]           # country/city code requested, if any
    session_id: Optional[str]    # set when this is a sticky session
    gateway: str                 # host:port, for logging

    def as_proxies(self) -> dict:
        """Shape that requests / httpx / cloudscraper expect."""
        return {"http": self.url, "https": self.url}


class ProxyProvider(ABC):
    """Common interface. The manager only ever talks to this."""

    name: str

    @abstractmethod
    def endpoint(
        self,
        *,
        geo: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ProxyEndpoint:
        """Return a proxy endpoint.

        session_id is None  -> a rotating exit IP (new IP per connection)
        session_id is set   -> a sticky exit IP tied to that id
        """
        raise NotImplementedError


@dataclass
class GatewayConfig:
    """Everything that differs between residential providers lives here.

    base_template / country_template / session_template are how the username
    is assembled. Defaults match the common Decodo/Oxylabs style; override via
    env vars for a provider that does it differently.
    """
    name: str
    gateway_host: str
    gateway_port: int
    username: str
    password: str
    scheme: str = "http"
    base_template: str = "{user}"
    country_template: str = "-country-{geo}"
    session_template: str = "-session-{session}"

    @classmethod
    def from_env(cls, prefix: str) -> "GatewayConfig":
        """Load a provider from env vars, e.g. prefix='DECODO' expects
        DECODO_HOST, DECODO_PORT, DECODO_USER, DECODO_PASS (templates optional).
        Keep real credentials in the environment, never in code or git.
        """
        def _req(key: str) -> str:
            val = os.environ.get(f"{prefix}_{key}")
            if not val:
                raise ValueError(f"Missing env var {prefix}_{key}")
            return val

        return cls(
            name=prefix.lower(),
            gateway_host=_req("HOST"),
            gateway_port=int(_req("PORT")),
            username=_req("USER"),
            password=_req("PASS"),
            scheme=os.environ.get(f"{prefix}_SCHEME", "http"),
            base_template=os.environ.get(f"{prefix}_BASE_TPL", "{user}"),
            country_template=os.environ.get(f"{prefix}_COUNTRY_TPL", "-country-{geo}"),
            session_template=os.environ.get(f"{prefix}_SESSION_TPL", "-session-{session}"),
        )


class ResidentialGatewayProvider(ProxyProvider):
    """Residential/mobile provider that selects IPs via username parameters."""

    def __init__(self, config: GatewayConfig):
        self.config = config
        self.name = config.name

    def _build_username(self, geo: Optional[str], session_id: Optional[str]) -> str:
        c = self.config
        username = c.base_template.format(user=c.username)
        if geo:
            username += c.country_template.format(geo=geo.lower())
        if session_id:
            username += c.session_template.format(session=session_id)
        return username

    def endpoint(self, *, geo=None, session_id=None) -> ProxyEndpoint:
        c = self.config
        username = self._build_username(geo, session_id)
        creds = f"{quote(username, safe='')}:{quote(c.password, safe='')}"
        gateway = f"{c.gateway_host}:{c.gateway_port}"
        return ProxyEndpoint(
            url=f"{c.scheme}://{creds}@{gateway}",
            provider=c.name,
            geo=geo,
            session_id=session_id,
            gateway=gateway,
        )
