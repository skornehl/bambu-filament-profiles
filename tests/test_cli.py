import json

import pytest

from bambu_filament_profiles import cli

from .conftest import FIXTURES


@pytest.fixture
def profiles(tmp_path):
    out = tmp_path / "profiles"
    lines = []
    code = cli.main(["build", "--cache", str(FIXTURES), "--lock", str(tmp_path / "lock.json"), "--manual", str(tmp_path / "manual"), "--out", str(out)], out=lines.append)
    assert code == 0 and "Profile unter" in lines[-1]
    return out


@pytest.fixture
def not_running(monkeypatch):
    monkeypatch.setattr(cli, "bambu_running", lambda: False)


def run(args, answers=(), interactive=True):
    lines = []
    queue = list(answers)
    ask = (lambda q: queue.pop(0) if queue else "") if interactive else None
    code = cli.main(args, ask=ask, out=lines.append)
    return code, "\n".join(lines)


def test_list(profiles):
    code, text = run(["list", "--profiles", str(profiles), "--vendor", "geeetech"])
    assert code == 0 and "Geeetech / PLA / PLA" in text


def test_install_requires_filter(profiles, fake_install, not_running):
    code, text = run(["install", "--profiles", str(profiles), "--data-dir", str(fake_install)])
    assert code == 1 and "auswählen" in text
    code, text = run(["install", "--profiles", str(profiles), "--vendor", "gibtsnicht", "--data-dir", str(fake_install)])
    assert code == 1 and "Keine passenden" in text


def test_install_dry_run_then_real(profiles, fake_install, tmp_path, not_running):
    base = fake_install / "user" / "123" / "filament" / "base"
    args = ["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--material", "PLA", "--data-dir", str(fake_install), "--backup-dir", str(tmp_path / "bk")]
    code, text = run(args + ["--dry-run"], answers=["1"])
    assert code == 0 and "Probelauf" in text and "[neu] Geeetech PLA @Bambu Lab P1S 0.4 nozzle" in text
    assert list(base.iterdir()) == []
    code, text = run(args + ["--user", "123"], answers=["n"])
    assert code == 1 and "Abgebrochen" in text
    code, text = run(args + ["--user", "123", "--yes"])
    assert code == 0 and "installiert" in text and "Backup" in text
    profile = json.loads((base / "Geeetech PLA @Bambu Lab P1S 0.4 nozzle.json").read_text(encoding="utf-8"))
    assert profile["inherits"] == "" and profile["filament_vendor"] == ["Geeetech"] and profile["filament_id"].startswith("P")
    assert (base / "Geeetech PLA @Bambu Lab P1S 0.4 nozzle.info").exists()
    assert list((tmp_path / "bk").glob("*.zip"))
    code, text = run(args + ["--user", "123", "--yes"])
    assert "unverändert" in text and "Nichts zu tun" in text


def test_install_conflicts(profiles, fake_install, tmp_path, not_running):
    base = fake_install / "user" / "123" / "filament" / "base"
    target = base / "Geeetech PLA @Bambu Lab P1S 0.4 nozzle.json"
    target.write_text(json.dumps({"name": target.stem, "inherits": "", "filament_id": "Pmine00"}), encoding="utf-8")
    args = ["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--name", "PLA", "--material", "PLA", "--data-dir", str(fake_install), "--user", "123", "--backup-dir", str(tmp_path / "bk")]
    code, text = run(args, answers=["n", "j"])  # Konflikt ablehnen, Rest bestätigen
    assert "übersprungen: Geeetech PLA @" in text
    assert json.loads(target.read_text(encoding="utf-8"))["filament_id"] == "Pmine00"
    code, text = run(args + ["--yes", "--overwrite"])
    assert code == 0
    overwritten = json.loads(target.read_text(encoding="utf-8"))
    assert overwritten["filament_id"] == "Pmine00" and overwritten["filament_vendor"] == ["Geeetech"]


def test_install_refuses_when_bambu_runs(profiles, fake_install, monkeypatch):
    monkeypatch.setattr(cli, "bambu_running", lambda: True)
    args = ["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--data-dir", str(fake_install), "--user", "123"]
    code, text = run(args + ["--yes"])
    assert code == 1 and "läuft" in text
    code, text = run(args + ["--dry-run"])
    assert code == 0 and "Achtung" in text


def test_install_non_interactive_needs_yes(profiles, fake_install, not_running):
    args = ["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--data-dir", str(fake_install), "--user", "123"]
    code, text = run(args, interactive=False)
    assert code == 1 and "--yes" in text


def test_install_without_system_profiles(profiles, tmp_path, not_running):
    data = tmp_path / "leer"
    (data / "user" / "default").mkdir(parents=True)
    code, text = run(["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--data-dir", str(data)])
    assert code == 1 and "Systemprofile" in text


def test_export(profiles, fake_install, tmp_path):
    out = tmp_path / "export"
    code, text = run(["export", "--profiles", str(profiles), "--vendor", "Geeetech", "--material", "PLA", "--name", "PLA", "--out", str(out), "--data-dir", str(fake_install)])
    assert code == 0 and "Konfigurationen importieren" in text
    exported = json.loads((out / "Geeetech PLA @Bambu Lab P1S 0.4 nozzle.json").read_text(encoding="utf-8"))
    assert exported["inherits"] == "" and exported["version"] == "2.9.0.81"
    code, text = run(["export", "--profiles", str(profiles), "--vendor", "Geeetech", "--out", str(tmp_path / "e2"), "--cache", str(FIXTURES)])
    assert code == 0 and "Quellen-Cache" in text
    code, text = run(["export", "--profiles", str(profiles), "--vendor", "nix", "--out", str(tmp_path / "e3")])
    assert code == 1


def test_export_reports_missing_parent(profiles, fake_install, tmp_path):
    spec_path = next(profiles.glob("Geeetech/PLA/PLA.json"))
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["inherits"] = "Fehlt"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    code, text = run(["export", "--profiles", str(profiles), "--vendor", "Geeetech", "--name", "PLA", "--material", "PLA", "--out", str(tmp_path / "e"), "--data-dir", str(fake_install)])
    assert "[FEHLER]" in text


@pytest.fixture
def user_presets(fake_install):
    filament = fake_install / "user" / "123" / "filament"
    (filament / "Alt PLA.json").write_text(json.dumps({"name": "Alt PLA", "inherits": "Generic PLA"}), encoding="utf-8")
    (filament / "Wolke PETG.json").write_text(json.dumps({"name": "Wolke PETG", "inherits": "Generic PETG"}), encoding="utf-8")
    (filament / "Wolke PETG.info").write_text("setting_id = PFUS9\n", encoding="utf-8")
    (filament / "kaputt.json").write_text("{", encoding="utf-8")
    return filament


def test_cleanup_lists_and_writes_checklist(fake_install, user_presets, tmp_path, not_running):
    checklist = tmp_path / "liste.md"
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--generic", "--list-file", str(checklist)])
    assert code == 0
    assert "[lokal] Alt PLA" in text and "[Cloud] Wolke PETG" in text and "Verwaltung von Batch-Profilen" in text
    assert "--delete-local" in text and "Hinweis: kaputt.json" in text
    assert "- [ ] Wolke PETG (Cloud" in checklist.read_text(encoding="utf-8")


def test_cleanup_delete_local(fake_install, user_presets, tmp_path, not_running):
    args = ["cleanup", "--data-dir", str(fake_install), "--user", "123", "--generic", "--delete-local", "--backup-dir", str(tmp_path / "bk")]
    code, text = run(args + ["--dry-run"])
    assert "würden gelöscht" in text and (user_presets / "Alt PLA.json").exists()
    code, text = run(args, answers=["n"])
    assert code == 1 and (user_presets / "Alt PLA.json").exists()
    code, text = run(args + ["--yes"])
    assert code == 0 and "1 lokale Profile gelöscht" in text
    assert not (user_presets / "Alt PLA.json").exists() and (user_presets / "Wolke PETG.json").exists()
    code, text = run(args + ["--yes"])
    assert "Keine lokalen Profile" in text


def test_cleanup_nothing_selected(fake_install, not_running):
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--from-tool"])
    assert code == 0 and "0 von 0" in text


def test_main_handles_errors(tmp_path):
    code, text = run(["cleanup", "--data-dir", str(tmp_path / "fehlt")])
    assert code == 1 and text.startswith("Fehler:")


def test_main_uses_input_when_tty(monkeypatch, fake_install, not_running):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: "")
    lines = []
    assert cli.main(["cleanup", "--data-dir", str(fake_install)], out=lines.append) == 0
    assert any("Benutzerordner: 123" in line for line in lines)


def test_fetch_command(monkeypatch, tmp_path):
    calls = []

    def fake_fetch_all(cache, lock, update, names, log):
        calls.append((cache, lock, update, names))
        return {"x": {"commit": "1"}} if update else lock

    monkeypatch.setattr(cli, "fetch_all", fake_fetch_all)
    lock = tmp_path / "lock.json"
    code, text = run(["fetch", "--cache", str(tmp_path), "--lock", str(lock)])
    assert code == 0 and not lock.exists()
    code, text = run(["fetch", "--cache", str(tmp_path), "--lock", str(lock), "--update", "--only", "x"])
    assert "Lock-Datei aktualisiert" in text and json.loads(lock.read_text())["x"]["commit"] == "1"
    assert calls[-1][3] == {"x"}


def test_cleanup_listing_ignores_running_bambu(fake_install, user_presets, monkeypatch):
    monkeypatch.setattr(cli, "bambu_running", lambda: True)
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123"])
    assert code == 0 and "Achtung" not in text
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--delete-local", "--yes"])
    assert code == 1 and "läuft" in text


def test_cleanup_not_for(fake_install, user_presets, not_running):
    (user_presets / "base").mkdir(exist_ok=True)
    (user_presets / "base" / "Acme PLA @Bambu Lab H2D 0.4 nozzle.json").write_text(json.dumps({"inherits": "", "filament_vendor": ["Acme"]}), encoding="utf-8")
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--not-for", "P1S"])
    assert code == 0 and "1 von 3" in text and "Drucker: H2D 0.4 nozzle" in text


def test_cleanup_printer_column(fake_install, user_presets, not_running, tmp_path):
    (user_presets / "Viele.json").write_text(json.dumps({"inherits": "Generic PLA", "compatible_printers": ["Bambu Lab P1S 0.4 nozzle", "Bambu Lab X1 0.4 nozzle", "Bambu Lab X1E 0.4 nozzle", "Bambu Lab A1 0.4 nozzle"]}), encoding="utf-8")
    (user_presets / "Waise.json").write_text(json.dumps({"inherits": "Fehlt"}), encoding="utf-8")
    (user_presets / "Frei.json").write_text(json.dumps({"inherits": ""}), encoding="utf-8")
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123"])
    assert "Drucker: P1S 0.4 nozzle, X1 0.4 nozzle, X1E 0.4 nozzle (+1)" in text
    assert "Waise — erbt von Fehlt, Hersteller: wie Fehlt, Drucker: unbekannt" in text
    assert "Frei — eigenständig, Hersteller: ?, Drucker: alle" in text
    data = tmp_path / "ohne-system"
    (data / "user" / "1" / "filament").mkdir(parents=True)
    code, text = run(["cleanup", "--data-dir", str(data)])
    assert code == 0 and "0 von 0" in text


def test_app_command(monkeypatch, profiles, fake_install, tmp_path):
    from bambu_filament_profiles import webapp

    seen = {}

    def fake_run(session, port, open_browser, out):
        seen.update(port=port, open_browser=open_browser, catalog=len(session.catalog), user=session.user)
        return 0

    monkeypatch.setattr(webapp, "run_app", fake_run)
    code, _ = run(["app", "--profiles", str(profiles), "--data-dir", str(fake_install), "--port", "9999", "--no-browser", "--backup-dir", str(tmp_path / "bk")])
    assert code == 0 and seen == {"port": 9999, "open_browser": False, "catalog": seen["catalog"], "user": "123"} and seen["catalog"] > 0
