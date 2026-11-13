"""Fetching an address someone typed, safely (P13, "Safety").

The MCP and API rails let a practice point the server at any address. Every
such request goes through `fetch`, which:

- **is https only**;
- **refuses private, loopback, link-local, multicast, reserved and cloud
  metadata addresses**, checked after DNS resolution (every address the name
  resolves to must be public) and **again on connect** (the socket's own peer
  address), so a name that resolves to something else the second time
  (rebinding) is still refused;
- connects to the address it checked, with the original host for TLS and the
  Host header;
- **follows no redirect off the original host** (and at most three on it);
- **caps time** (per step and overall) **and response size**;
- says every failure in plain words (`FetchRefused`, `FetchFailed`), never
  echoing a secret it sent.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlencode, urljoin, urlsplit

TIMEOUT = 10.0
OVERALL = 25.0
MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
METADATA_HOSTS = {"metadata.google.internal", "metadata", "metadata.goog",
                  "instance-data", "instance-data.ec2.internal"}
METADATA_ADDRESSES = {ipaddress.ip_address("169.254.169.254"),
                      ipaddress.ip_address("169.254.170.2"),
                      ipaddress.ip_address("100.100.100.200"),
                      ipaddress.ip_address("fd00:ec2::254")}


class FetchRefused(ValueError):
    """The address is one the app will not fetch: said why."""


class FetchFailed(Exception):
    """The fetch was allowed but did not work: said why."""


def public(address) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip in METADATA_ADDRESSES:
        return False
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast \
            or ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return False
    return ip.is_global


def resolve(host: str, port: int) -> list[str]:
    """Every address `host` resolves to; refused unless every one is public."""
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if host.lower().rstrip(".") in METADATA_HOSTS:
        raise FetchRefused("That address is a cloud metadata service; it can't be used.")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchFailed(f"{host} couldn't be found. Check the address.") from None
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise FetchFailed(f"{host} couldn't be found. Check the address.")
    bad = [a for a in addresses if not public(a)]
    if bad:
        what = "That address" if literal else f"{host} points to an address that"
        raise FetchRefused(f"{what} is private or internal; only public addresses can be used.")
    return addresses


def check_url(url: str) -> tuple[str, int, str]:
    """(host, port, path-and-query) of an https address, or refused in words."""
    parts = urlsplit(str(url or "").strip())
    if parts.scheme != "https":
        raise FetchRefused("Only https addresses can be used.")
    if not parts.hostname:
        raise FetchRefused("That isn't a complete address.")
    if parts.username or parts.password:
        raise FetchRefused("Put credentials in the connection's secret, not in the address.")
    try:
        port = parts.port or 443
    except ValueError:
        raise FetchRefused("That address has a port that isn't a number.") from None
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parts.hostname, port, path


class _PinnedConnection(http.client.HTTPSConnection):
    """Connects to the address already checked, and checks the socket's own
    peer address again once connected."""

    def __init__(self, host, port, address, timeout):
        super().__init__(host, port, timeout=timeout,
                         context=ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, self.port), self.timeout)
        peer = sock.getpeername()[0]
        if not public(peer):
            sock.close()
            raise FetchRefused("The address changed to a private or internal one on "
                               "connecting; it can't be used.")
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def connection_for(host, port, address, timeout):
    """Overridable in tests: the pinned connection to one checked address."""
    return _PinnedConnection(host, port, address, timeout)


def fetch(method: str, url: str, *, headers=None, query=None, body: bytes | None = None,
          max_bytes: int = MAX_BYTES, timeout: float = TIMEOUT,
          overall: float = OVERALL) -> tuple[int, dict, bytes]:
    """(status, headers, body) of one request, under every rule above."""
    method = method.upper()
    if method not in ("GET", "POST"):
        raise FetchRefused("Only GET and POST are used.")
    if query:
        url += ("&" if "?" in url else "?") + urlencode(query)
    deadline = time.monotonic() + overall
    host, port, path = check_url(url)
    first_host = host
    for _ in range(MAX_REDIRECTS + 1):
        address = resolve(host, port)[0]
        left = deadline - time.monotonic()
        if left <= 0:
            raise FetchFailed("The server took too long to answer.")
        conn = connection_for(host, port, address, min(timeout, left))
        try:
            sent = dict(headers or {})
            sent.setdefault("User-Agent", "Execs-NOW-HQ-feeds/1")
            sent["Host"] = host if port == 443 else f"{host}:{port}"
            conn.request(method, path, body=body, headers=sent)
            response = conn.getresponse()
            status = response.status
            answer_headers = {k.lower(): v for k, v in response.getheaders()}
            if status in (301, 302, 303, 307, 308):
                location = answer_headers.get("location") or ""
                target = urljoin(f"https://{host}:{port}{path}", location)
                host, port, path = check_url(target)
                if host != first_host:
                    raise FetchRefused("The server redirected to another host; that isn't "
                                       "followed.")
                if status == 303:
                    method, body = "GET", None
                continue
            length = answer_headers.get("content-length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise FetchFailed(f"The answer is larger than {max_bytes // 1000} KB.")
            data = b""
            while True:
                if time.monotonic() > deadline:
                    raise FetchFailed("The server took too long to answer.")
                chunk = response.read(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > max_bytes:
                    raise FetchFailed(f"The answer is larger than {max_bytes // 1000} KB.")
            return status, answer_headers, data
        except (socket.timeout, TimeoutError):
            raise FetchFailed("The server took too long to answer.") from None
        except ssl.SSLError:
            raise FetchFailed("The server's https certificate couldn't be checked.") from None
        except (ConnectionError, OSError, http.client.HTTPException) as exc:
            if isinstance(exc, (FetchRefused, FetchFailed)):
                raise
            raise FetchFailed("The server couldn't be reached.") from None
        finally:
            conn.close()
    raise FetchFailed("The server redirected too many times.")


def json_path(data, path: str):
    """The value at a dotted path with [n] indexes: `data.total`,
    `items[0].count`, `result.rows[-1].value`. None when it isn't there."""
    import re

    path = str(path or "").strip()
    if not path:
        return data
    current = data
    for part in re.findall(r"[^.\[\]]+|\[-?\d+\]", path):
        if part.startswith("["):
            index = int(part[1:-1])
            if not isinstance(current, list) or not -len(current) <= index < len(current):
                return None
            current = current[index]
        else:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
    return current
