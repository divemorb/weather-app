"""Fake upstream server for the contract suite (stdlib only).

Serves recorded or synthetic responses for Bright Sky (``/bs/...``),
Open-Meteo (``/om/v1/...``, ``/ens/v1/...``) and Nominatim (``/nom/...``),
and logs every request (path, query, User-Agent) so the suite can compare
what each backend asked for. Query parameters are ignored when choosing
the response: a scenario fixes the data, the request log is compared
separately.

Response specs (per path, from the scenario):

* ``{"file": "live/radar.json"}``: that fixture file (relative to fixtures/)
* ``{"status": 500}``: an HTTP error with a short text body
* ``{"raw": "text"}``: status 200 with this body (e.g. broken JSON)
* ``{"oversize": 6000000, "declare": true}``: a body of that many bytes;
  with ``declare`` the Content-Length header says so, without it the body
  is sent close-delimited (no length), so the reader must count
"""
from __future__ import annotations

import http.server
import pathlib
import threading
import time
import urllib.parse

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


class FakeUpstream:
    def __init__(self, routes: dict[str, dict]):
        self.routes = routes
        self.log: list[dict] = []
        self.lock = threading.Lock()
        self.last_request = 0.0
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def requests(self) -> list[str]:
        """The request log as sorted, comparable strings."""
        out = []
        with self.lock:
            entries = list(self.log)
        for e in entries:
            query = "&".join(f"{k}={v}" for k, v in sorted(e["query"]))
            ua = f" UA={e['ua']}" if e["path"].startswith("/nom/") else ""
            out.append(f"{e['path']}?{query}{ua}")
        return sorted(out)

    def wait_idle(self, quiet: float = 1.0, timeout: float = 30.0):
        """Wait until no request has arrived for ``quiet`` seconds."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if time.monotonic() - self.last_request >= quiet:
                return
            time.sleep(0.1)

    def _handler(self):
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                with fake.lock:
                    fake.log.append({"path": url.path,
                                     "query": urllib.parse.parse_qsl(url.query, keep_blank_values=True),
                                     "ua": self.headers.get("User-Agent", "")})
                    fake.last_request = time.monotonic()
                spec = fake.routes.get(url.path)
                try:
                    self._respond(spec)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the backend gave up reading (e.g. the size cap): expected
                fake.last_request = time.monotonic()

            def _respond(self, spec):
                if spec is None:
                    return self._send(404, b"not found", "text/plain")
                if "file" in spec:
                    return self._send(200, (FIXTURES / spec["file"]).read_bytes(), "application/json")
                if "status" in spec:
                    return self._send(spec["status"], b"upstream failure", "text/plain")
                if "raw" in spec:
                    return self._send(200, spec["raw"].encode(), "application/json")
                if "oversize" in spec:
                    n = spec["oversize"]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    if spec.get("declare"):
                        self.send_header("Content-Length", str(n))
                    self.end_headers()
                    chunk = b"[" + b"0," * 32767 + b"0"
                    sent = 0
                    while sent < n:
                        self.wfile.write(chunk)
                        sent += len(chunk)
                    return None
                raise ValueError(f"bad response spec {spec!r}")

            def _send(self, status, body, ctype):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler
