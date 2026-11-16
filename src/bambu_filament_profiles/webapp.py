"""Lokale Web-Oberfläche der Begleit-App (``bfp app``).

Ein kleiner HTTP-Server aus der Standardbibliothek, nur auf 127.0.0.1. Schutz
gegen fremde Webseiten im selben Browser:

* jede API-Anfrage braucht das Zufalls-Token dieser Sitzung (Header ``X-BFP-Token``);
* der ``Host``-Header muss ``127.0.0.1:<port>`` oder ``localhost:<port>`` sein
  (gegen DNS-Rebinding);
* Schreibaktionen nur per POST mit JSON.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .appmodel import AppSession
from .install import InstallError

INDEX_HTML = Path(__file__).parent / "web" / "index.html"
MAX_BODY = 1_000_000


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, session: AppSession, host: str = "127.0.0.1", port: int = 0):
        super().__init__((host, port), Handler)
        self.session = session
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    server_version = "bfp"

    def log_message(self, format, *args):  # noqa: A002 - ruhig bleiben
        pass

    # ----------------------------------------------------------- Hilfen

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        return host in {f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}"}

    def _token_ok(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-BFP-Token", ""), self.server.token)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Anfrage zu groß")
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise ValueError("JSON erwartet")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("JSON-Objekt erwartet")
        return data

    # ---------------------------------------------------------- Anfragen

    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            return self._json(403, {"error": "Falscher Host"})
        parts = urlsplit(self.path)
        if parts.path == "/":
            html = INDEX_HTML.read_text(encoding="utf-8").replace("__BFP_TOKEN__", self.server.token)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if not self._token_ok():
            return self._json(403, {"error": "Token fehlt"})
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        session = self.server.session
        try:
            with self.server.lock:
                if parts.path == "/api/state":
                    return self._json(200, session.state())
                if parts.path == "/api/profiles":
                    return self._json(200, session.profiles())
                if parts.path == "/api/profile":
                    return self._json(200, session.profile(int(query.get("id", "-1"))))
                if parts.path == "/api/existing":
                    return self._json(
                        200,
                        session.existing(generic=query.get("generic") == "1", not_for=query.get("not_for", ""), text=query.get("q", "")),
                    )
        except (InstallError, ValueError) as exc:
            return self._json(400, {"error": str(exc)})
        return self._json(404, {"error": "Nicht gefunden"})

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            return self._json(403, {"error": "Falscher Host"})
        if not self._token_ok():
            return self._json(403, {"error": "Token fehlt"})
        session = self.server.session
        try:
            body = self._body()
            with self.server.lock:
                path = urlsplit(self.path).path
                if path == "/api/select":
                    session.select(body.get("installation"), body.get("user"))
                    return self._json(200, session.state())
                if path == "/api/plan":
                    return self._json(200, session.plan([int(i) for i in body.get("ids", [])]))
                if path == "/api/install":
                    return self._json(200, session.install([int(i) for i in body.get("ids", [])], body.get("overwrite", [])))
                if path == "/api/delete-local":
                    return self._json(200, session.delete_local(body.get("names", [])))
                if path == "/api/checklist":
                    return self._json(200, {"markdown": session.checklist(body.get("names", []))})
                if path == "/api/shutdown":
                    self._json(200, {"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return None
        except (InstallError, ValueError) as exc:
            return self._json(400, {"error": str(exc)})
        return self._json(404, {"error": "Nicht gefunden"})


def make_server(session: AppSession, port: int = 8765) -> AppServer:
    """Server auf dem Wunsch-Port, sonst auf einem freien Port."""
    try:
        return AppServer(session, port=port)
    except OSError:
        return AppServer(session, port=0)


def run_app(session: AppSession, port: int = 8765, open_browser: bool = True, out=print) -> int:
    server = make_server(session, port)
    out(f"Begleit-App läuft auf {server.url}")
    out("Beenden mit dem Knopf „Beenden“ in der App oder mit Strg+C.")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interaktiv
        pass
    finally:
        server.server_close()
    out("Begleit-App beendet")
    return 0
