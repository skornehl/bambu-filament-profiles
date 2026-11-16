import http.client
import json
import threading

import pytest

from bambu_filament_profiles import webapp
from bambu_filament_profiles.appmodel import AppSession
from bambu_filament_profiles.catalog import build, write_output

from .conftest import PRINTER


@pytest.fixture
def server(tmp_path, records, bambu, fake_install):
    profiles = tmp_path / "profiles"
    write_output(build(records, bambu, PRINTER), profiles, {}, PRINTER)
    filament = fake_install / "user" / "123" / "filament"
    (filament / "Alt PLA.json").write_text(json.dumps({"inherits": "Generic PLA"}), encoding="utf-8")
    session = AppSession(profiles, tmp_path / "bk", data_dir=str(fake_install), running=lambda: False)
    srv = webapp.make_server(session, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def call(srv, method, path, body=None, token=True, host=None, content_type="application/json"):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{srv.port}"}
    if token:
        headers["X-BFP-Token"] = srv.token if token is True else token
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers["Content-Type"] = content_type
    conn.request(method, path, body=data, headers=headers)
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    try:
        return res.status, json.loads(raw)
    except ValueError:
        return res.status, raw.decode()


def test_index_embeds_token_and_security_headers(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    conn.request("GET", "/", headers={"Host": f"localhost:{server.port}"})
    res = conn.getresponse()
    html = res.read().decode()
    assert res.status == 200 and server.token in html and "__BFP_TOKEN__" not in html
    assert res.getheader("X-Frame-Options") == "DENY" and res.getheader("Cache-Control") == "no-store"
    assert server.url == f"http://127.0.0.1:{server.port}/"


def test_rejects_wrong_host_and_missing_token(server):
    assert call(server, "GET", "/", host="evil.example:80")[0] == 403
    assert call(server, "GET", "/api/state", token=False)[0] == 403
    assert call(server, "GET", "/api/state", token="falsch")[0] == 403
    assert call(server, "POST", "/api/install", {"ids": [0]}, token=False)[0] == 403
    assert call(server, "POST", "/api/install", {"ids": [0]}, host="evil.example")[0] == 403


def test_get_endpoints(server):
    status, state = call(server, "GET", "/api/state")
    assert status == 200 and state["user"] == "123"
    status, profiles = call(server, "GET", "/api/profiles")
    item = next(p for p in profiles if p["brand"] == "Geeetech" and p["product"] == "PLA")
    status, detail = call(server, "GET", f"/api/profile?id={item['id']}")
    assert status == 200 and detail["parent"] == "Generic PLA"
    assert call(server, "GET", "/api/profile?id=99999")[0] == 400
    assert call(server, "GET", "/api/profile?id=abc")[0] == 400
    status, existing = call(server, "GET", "/api/existing?generic=1&q=alt")
    assert [p["name"] for p in existing["presets"]] == ["Alt PLA"]
    assert call(server, "GET", "/api/gibtsnicht")[0] == 404


def test_post_flow(server):
    profiles = call(server, "GET", "/api/profiles")[1]
    item = next(p for p in profiles if p["brand"] == "Geeetech" and p["product"] == "PLA")
    status, plan = call(server, "POST", "/api/plan", {"ids": [item["id"]]})
    assert status == 200 and plan["actions"][0]["kind"] == "new"
    status, result = call(server, "POST", "/api/install", {"ids": [item["id"]], "overwrite": []})
    assert status == 200 and result["installed"] == [item["name"]]
    status, md = call(server, "POST", "/api/checklist", {"names": ["Alt PLA"]})
    assert "- [ ] Alt PLA" in md["markdown"]
    status, deleted = call(server, "POST", "/api/delete-local", {"names": ["Alt PLA"]})
    assert deleted["deleted"] == ["Alt PLA"]
    status, state = call(server, "POST", "/api/select", {"user": "default"})
    assert state["user"] == "default"
    assert call(server, "POST", "/api/select", {"user": "999"})[0] == 400
    assert call(server, "POST", "/api/nix", {})[0] == 404


def test_post_validation(server):
    assert call(server, "POST", "/api/plan", b"[1, 2]")[0] == 400
    assert call(server, "POST", "/api/plan", b"{}", content_type="text/plain")[0] == 400
    assert call(server, "POST", "/api/plan", {"ids": []})[0] == 400
    big = b"{" + b" " * (webapp.MAX_BODY + 1) + b"}"
    assert call(server, "POST", "/api/plan", big)[0] == 400


def test_shutdown_endpoint(tmp_path, records, bambu, fake_install):
    profiles = tmp_path / "p"
    write_output(build(records, bambu, PRINTER), profiles, {}, PRINTER)
    srv = webapp.make_server(AppSession(profiles, tmp_path / "bk", data_dir=str(fake_install), running=lambda: False), port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    assert call(srv, "POST", "/api/shutdown", {})[1] == {"ok": True}
    thread.join(timeout=5)
    assert not thread.is_alive()
    srv.server_close()


def test_make_server_falls_back_to_free_port(server):
    other = webapp.make_server(server.session, port=server.port)
    assert other.port != server.port
    other.server_close()


def test_run_app_opens_browser_and_stops(monkeypatch, tmp_path, records, bambu, fake_install):
    profiles = tmp_path / "p"
    write_output(build(records, bambu, PRINTER), profiles, {}, PRINTER)
    session = AppSession(profiles, tmp_path / "bk", data_dir=str(fake_install), running=lambda: False)
    opened = []
    monkeypatch.setattr(webapp.webbrowser, "open", opened.append)
    monkeypatch.setattr(webapp.AppServer, "serve_forever", lambda self: None)
    lines = []
    assert webapp.run_app(session, port=0, out=lines.append) == 0
    assert opened and opened[0].startswith("http://127.0.0.1:") and "beendet" in lines[-1]
    assert webapp.run_app(session, port=0, open_browser=False, out=lines.append) == 0
