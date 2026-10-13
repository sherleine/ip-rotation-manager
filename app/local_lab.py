"""Local-only target and mock HTTP proxies for safe development/testing."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit
from urllib.request import urlopen

from app.config import HOST, TARGET_HOSTNAME, TARGET_PORT, PROXY_PORTS


class ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _serve(server):
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def start_target():
    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                body, status = b"ok", 200
            elif self.path == "/":
                body, status = b'{"service":"local-test-target","status":"ok"}', 200
            else:
                body, status = b"not found", 404
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ReusableHTTPServer((HOST, TARGET_PORT), TargetHandler)
    _serve(server)
    return server


def start_mock_proxy(port: int, name: str):
    """Forward only to the configured lab target; reject other destinations."""
    allowed_host = f"{TARGET_HOSTNAME}:{TARGET_PORT}"

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            raw = self.path
            if raw.startswith("http://") or raw.startswith("https://"):
                parsed = urlsplit(raw)
                requested_host = parsed.netloc
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
            else:
                requested_host = self.headers.get("Host", "")
                path = raw

            if requested_host != allowed_host:
                body = b"blocked: mock proxy only permits the local test target"
                self.send_response(403)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            try:
                # The lab proxy connects to the actual localhost target. The special
                # target hostname is used only by the client to ensure proxy routing.
                with urlopen(f"http://{HOST}:{TARGET_PORT}{path}", timeout=1.5) as upstream:
                    body = upstream.read(64 * 1024)
                    status = upstream.status
                    content_type = upstream.headers.get(
                        "Content-Type", "application/octet-stream"
                    )
            except Exception:
                body, status, content_type = b"upstream error", 502, "text/plain"

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Mock-Proxy", name)
            self.end_headers()
            self.wfile.write(body)

        def do_CONNECT(self):
            self.send_error(501, "HTTPS CONNECT is intentionally not implemented in this MVP")

        def log_message(self, *_args):
            pass

    server = ReusableHTTPServer((HOST, port), ProxyHandler)
    _serve(server)
    return server


def start_lab():
    target = start_target()
    proxies = [
        start_mock_proxy(port, f"mock-{index + 1}")
        for index, port in enumerate(PROXY_PORTS)
    ]
    return [target, *proxies]


def stop_lab(servers):
    for server in reversed(servers):
        server.shutdown()
        server.server_close()
