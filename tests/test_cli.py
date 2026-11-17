import json

import pytest

from bambu_filament_profiles import catalog, cli
from bambu_filament_profiles.catalog import build, load_records, write_output
from bambu_filament_profiles.fetch import FetchError
from bambu_filament_profiles.install import default_data_dir
from bambu_filament_profiles.sources.bambu import BambuProfiles

from .conftest import FIXTURES


@pytest.fixture
def profiles(tmp_path):
    out = tmp_path / "profiles"
    lines = []
    code = cli.main(["build", "--cache", str(FIXTURES), "--lock", str(tmp_path / "lock.json"), "--manual", str(tmp_path / "manual"), "--out", str(out)], out=lines.append)
    assert code == 0 and "profiles written to" in lines[-1]
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
    assert code == 1 and "please select" in text
    code, text = run(["install", "--profiles", str(profiles), "--vendor", "nothing", "--data-dir", str(fake_install)])
    assert code == 1 and "No matching" in text


def test_install_dry_run_then_real(profiles, fake_install, tmp_path, not_running):
    base = fake_install / "user" / "123" / "filament" / "base"
    args = ["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--material", "PLA", "--data-dir", str(fake_install), "--backup-dir", str(tmp_path / "bk")]
    code, text = run(args + ["--dry-run"], answers=["1"])
    assert code == 0 and "Dry run" in text and "[new] Geeetech PLA @Bambu Lab P1S 0.4 nozzle" in text
    assert list(base.iterdir()) == []
    code, text = run(args + ["--user", "123"], answers=["n"])
    assert code == 1 and "Cancelled" in text
    code, text = run(args + ["--user", "123", "--yes"])
    assert code == 0 and "installed" in text and "Backup" in text
    profile = json.loads((base / "Geeetech PLA @Bambu Lab P1S 0.4 nozzle.json").read_text(encoding="utf-8"))
    assert profile["inherits"] == "" and profile["filament_vendor"] == ["Geeetech"] and profile["filament_id"].startswith("P")
    assert (base / "Geeetech PLA @Bambu Lab P1S 0.4 nozzle.info").exists()
    assert list((tmp_path / "bk").glob("*.zip"))
    code, text = run(args + ["--user", "123", "--yes"])
    assert "unchanged" in text and "Nothing to do" in text


def test_install_conflicts(profiles, fake_install, tmp_path, not_running):
    base = fake_install / "user" / "123" / "filament" / "base"
    target = base / "Geeetech PLA @Bambu Lab P1S 0.4 nozzle.json"
    target.write_text(json.dumps({"name": target.stem, "inherits": "", "filament_id": "Pmine00"}), encoding="utf-8")
    args = ["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--name", "PLA", "--material", "PLA", "--data-dir", str(fake_install), "--user", "123", "--backup-dir", str(tmp_path / "bk")]
    code, text = run(args, answers=["n", "y"])  # decline the conflict, confirm the rest
    assert "skipped: Geeetech PLA @" in text
    assert json.loads(target.read_text(encoding="utf-8"))["filament_id"] == "Pmine00"
    code, text = run(args + ["--yes", "--overwrite"])
    assert code == 0
    overwritten = json.loads(target.read_text(encoding="utf-8"))
    assert overwritten["filament_id"] == "Pmine00" and overwritten["filament_vendor"] == ["Geeetech"]


def test_install_refuses_when_bambu_runs(profiles, fake_install, monkeypatch):
    monkeypatch.setattr(cli, "bambu_running", lambda: True)
    args = ["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--data-dir", str(fake_install), "--user", "123"]
    code, text = run(args + ["--yes"])
    assert code == 1 and "running" in text
    code, text = run(args + ["--dry-run"])
    assert code == 0 and "Warning" in text


def test_install_non_interactive_needs_yes(profiles, fake_install, not_running):
    args = ["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--data-dir", str(fake_install), "--user", "123"]
    code, text = run(args, interactive=False)
    assert code == 1 and "--yes" in text


def test_install_without_system_profiles(profiles, tmp_path, not_running):
    data = tmp_path / "empty"
    (data / "user" / "default").mkdir(parents=True)
    code, text = run(["install", "--profiles", str(profiles), "--vendor", "Geeetech", "--data-dir", str(data)])
    assert code == 1 and "system profiles" in text


def test_export(profiles, fake_install, tmp_path):
    out = tmp_path / "export"
    code, text = run(["export", "--profiles", str(profiles), "--vendor", "Geeetech", "--material", "PLA", "--name", "PLA", "--out", str(out), "--data-dir", str(fake_install)])
    assert code == 0 and "Import Configs" in text
    exported = json.loads((out / "Geeetech PLA @Bambu Lab P1S 0.4 nozzle.json").read_text(encoding="utf-8"))
    assert exported["inherits"] == "" and exported["version"] == "2.9.0.81"
    code, text = run(["export", "--profiles", str(profiles), "--vendor", "Geeetech", "--out", str(tmp_path / "e2"), "--cache", str(FIXTURES)])
    assert code == 0 and "source cache" in text
    code, text = run(["export", "--profiles", str(profiles), "--vendor", "nothing", "--out", str(tmp_path / "e3")])
    assert code == 1


def test_export_reports_missing_parent(profiles, fake_install, tmp_path):
    spec_path = next(profiles.glob("Geeetech/PLA/PLA.json"))
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["inherits"] = "Missing"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    code, text = run(["export", "--profiles", str(profiles), "--vendor", "Geeetech", "--name", "PLA", "--material", "PLA", "--out", str(tmp_path / "e"), "--data-dir", str(fake_install)])
    assert "[ERROR]" in text


@pytest.fixture
def user_presets(fake_install):
    filament = fake_install / "user" / "123" / "filament"
    (filament / "Old PLA.json").write_text(json.dumps({"name": "Old PLA", "inherits": "Generic PLA"}), encoding="utf-8")
    (filament / "Cloud PETG.json").write_text(json.dumps({"name": "Cloud PETG", "inherits": "Generic PETG"}), encoding="utf-8")
    (filament / "Cloud PETG.info").write_text("setting_id = PFUS9\n", encoding="utf-8")
    (filament / "broken.json").write_text("{", encoding="utf-8")
    return filament


def test_cleanup_lists_and_writes_checklist(fake_install, user_presets, tmp_path, not_running):
    checklist = tmp_path / "list.md"
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--generic", "--list-file", str(checklist)])
    assert code == 0
    assert "[local] Old PLA" in text and "[cloud] Cloud PETG" in text and "Batch Preset Management" in text
    assert "--delete-local" in text and "Note: broken.json" in text
    assert "- [ ] Cloud PETG (cloud" in checklist.read_text(encoding="utf-8")


def test_cleanup_delete_local(fake_install, user_presets, tmp_path, not_running):
    args = ["cleanup", "--data-dir", str(fake_install), "--user", "123", "--generic", "--delete-local", "--backup-dir", str(tmp_path / "bk")]
    code, text = run(args + ["--dry-run"])
    assert "would be deleted" in text and (user_presets / "Old PLA.json").exists()
    code, text = run(args, answers=["n"])
    assert code == 1 and (user_presets / "Old PLA.json").exists()
    code, text = run(args + ["--yes"])
    assert code == 0 and "1 local profiles deleted" in text
    assert not (user_presets / "Old PLA.json").exists() and (user_presets / "Cloud PETG.json").exists()
    code, text = run(args + ["--yes"])
    assert "No local profiles" in text


def test_cleanup_nothing_selected(fake_install, not_running):
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--from-tool"])
    assert code == 0 and "0 of 0" in text


def test_main_handles_errors(tmp_path):
    code, text = run(["cleanup", "--data-dir", str(tmp_path / "missing")])
    assert code == 1 and text.startswith("Error:")


def test_main_uses_input_when_tty(monkeypatch, fake_install, not_running):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: "")
    lines = []
    assert cli.main(["cleanup", "--data-dir", str(fake_install)], out=lines.append) == 0
    assert any("User folder: 123" in line for line in lines)


def test_fetch_command(monkeypatch, tmp_path):
    calls = []

    def fake_fetch_all(cache, lock, update, names, log):
        calls.append((cache, lock, update, names))
        return {"x": {"commit": "1"}} if update else lock

    monkeypatch.setattr(cli, "fetch_all", fake_fetch_all)
    lock = tmp_path / "lock.json"
    code, text = run(["fetch", "--cache", str(tmp_path), "--lock", str(lock), "--pinned"])
    assert code == 0 and not lock.exists() and calls[-1][2] is False
    code, text = run(["fetch", "--cache", str(tmp_path), "--lock", str(lock), "--only", "x"])
    assert "Lock file updated" in text and json.loads(lock.read_text())["x"]["commit"] == "1"
    assert calls[-1][2] is True and calls[-1][3] == {"x"}


def test_update_command(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "fetch_all", lambda cache, lock, update, log: {"ofd": {"commit": "a" * 40, "license": "MIT"}})
    out = tmp_path / "p"
    args = ["update", "--cache", str(FIXTURES), "--lock", str(tmp_path / "lock.json"), "--manual", str(tmp_path / "manual"), "--out", str(out)]
    code, text = run(args)
    assert code == 0 and "profiles written to" in text and (out / "BUILD.json").exists()
    code, text = run(["list", "--profiles", str(out), "--vendor", "geeetech"])
    assert code == 0 and "Note" not in text and "Geeetech / PLA / PLA" in text


def fake_update(seen):
    def update(cache, lock, manual, out_dir, printer, log):
        seen.append((cache, lock, out_dir))
        result = build(load_records(FIXTURES, None, printer, log=log), BambuProfiles(FIXTURES / "bambu"), printer)
        write_output(result, out_dir, {}, printer)
        return result

    return update


def test_first_use_builds_catalog_locally(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "update_profiles", fake_update(seen))
    code, text = run(["list", "--vendor", "geeetech"])
    data = default_data_dir()
    assert code == 0 and "No profiles on this computer yet" in text and "Geeetech / PLA / PLA" in text
    assert seen == [(data / "sources", data / "sources.lock.json", data / "profiles")]
    code, text = run(["list", "--vendor", "geeetech"])
    assert len(seen) == 1 and "No profiles" not in text and "Note" not in text


def test_other_profile_folder_is_not_built_implicitly(tmp_path):
    code, text = run(["list", "--profiles", str(tmp_path / "empty")])
    assert code == 1 and "bfp update --out" in text


def test_hint_for_old_or_outdated_catalog(profiles):
    info = json.loads((profiles / "BUILD.json").read_text(encoding="utf-8"))
    info["built"] = "2020-01-01T00:00:00+00:00"
    (profiles / "BUILD.json").write_text(json.dumps(info), encoding="utf-8")
    code, text = run(["list", "--profiles", str(profiles), "--vendor", "geeetech"])
    assert code == 0 and "days old" in text
    (profiles / "BUILD.json").unlink()
    code, text = run(["list", "--profiles", str(profiles), "--vendor", "geeetech"])
    assert code == 0 and "older version" in text and "Geeetech / PLA / PLA" in text


def test_outdated_default_catalog_is_rebuilt(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "update_profiles", fake_update(seen))
    run(["list"])
    build_file = default_data_dir() / "profiles" / "BUILD.json"
    info = json.loads(build_file.read_text(encoding="utf-8"))
    info["format"] = 1  # catalog from v0.2.0
    build_file.write_text(json.dumps(info), encoding="utf-8")
    code, text = run(["list", "--vendor", "geeetech"])
    assert code == 0 and "older version: rebuilding" in text and len(seen) == 2


def test_fetch_errors_are_reported(monkeypatch):
    def broken(*args, **kwargs):
        raise FetchError("git not found")

    monkeypatch.setattr(cli, "update_profiles", broken)
    code, text = run(["update"])
    assert code == 1 and "Error: git not found" in text


def test_cleanup_listing_ignores_running_bambu(fake_install, user_presets, monkeypatch):
    monkeypatch.setattr(cli, "bambu_running", lambda: True)
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123"])
    assert code == 0 and "Warning" not in text
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--delete-local", "--yes"])
    assert code == 1 and "running" in text


def test_cleanup_not_for(fake_install, user_presets, not_running):
    (user_presets / "base").mkdir(exist_ok=True)
    (user_presets / "base" / "Acme PLA @Bambu Lab H2D 0.4 nozzle.json").write_text(json.dumps({"inherits": "", "filament_vendor": ["Acme"]}), encoding="utf-8")
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--not-for", "P1S"])
    assert code == 0 and "1 of 3" in text and "printers: H2D 0.4 nozzle" in text


def test_cleanup_printer_column(fake_install, user_presets, not_running, tmp_path):
    (user_presets / "Many.json").write_text(json.dumps({"inherits": "Generic PLA", "compatible_printers": ["Bambu Lab P1S 0.4 nozzle", "Bambu Lab X1 0.4 nozzle", "Bambu Lab X1E 0.4 nozzle", "Bambu Lab A1 0.4 nozzle"]}), encoding="utf-8")
    (user_presets / "Orphan.json").write_text(json.dumps({"inherits": "Missing"}), encoding="utf-8")
    (user_presets / "Free.json").write_text(json.dumps({"inherits": ""}), encoding="utf-8")
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123"])
    assert "printers: P1S 0.4 nozzle, X1 0.4 nozzle, X1E 0.4 nozzle (+1)" in text
    assert "Orphan — inherits Missing, brand: as Missing, printers: unknown" in text
    assert "Free — standalone, brand: ?, printers: all" in text
    data = tmp_path / "no-system"
    (data / "user" / "1" / "filament").mkdir(parents=True)
    code, text = run(["cleanup", "--data-dir", str(data)])
    assert code == 0 and "0 of 0" in text


def test_app_command(monkeypatch, profiles, fake_install, tmp_path):
    from bambu_filament_profiles import webapp

    seen = {}

    def fake_run(session, port, open_browser, out):
        seen.update(port=port, open_browser=open_browser, catalog=len(session.catalog), user=session.user, session=session)
        return 0

    monkeypatch.setattr(webapp, "run_app", fake_run)
    code, _ = run(["app", "--profiles", str(profiles), "--data-dir", str(fake_install), "--port", "9999", "--no-browser", "--backup-dir", str(tmp_path / "bk")])
    session = seen.pop("session")
    assert code == 0 and seen == {"port": 9999, "open_browser": False, "catalog": seen["catalog"], "user": "123"} and seen["catalog"] > 0
    assert session.state()["can_update"]
    updates = []
    monkeypatch.setattr(cli, "update_profiles", fake_update(updates))
    assert session.update()["catalog_size"] == seen["catalog"] and updates[0][2] == profiles


@pytest.fixture
def split_brands(fake_install):
    base = fake_install / "user" / "123" / "filament" / "base"
    for name, vendor, setting in (("Overture 3D PLA @X", "Overture 3D", "PFUS1"), ("Overture 3D PETG @X", "Overture 3D", "")):
        (base / f"{name}.json").write_text(json.dumps({"name": name, "inherits": "", "filament_vendor": [vendor]}), encoding="utf-8")
        (base / f"{name}.info").write_text(f"setting_id = {setting}\n", encoding="utf-8")
    return base


def test_cleanup_merges_brand_spellings(fake_install, split_brands, tmp_path, not_running):
    args = ["cleanup", "--data-dir", str(fake_install), "--user", "123", "--backup-dir", str(tmp_path / "bk")]
    code, text = run(args)
    assert code == 0 and "Overture 3D → Overture (Bambu Studio): 2 of your profiles" in text
    code, text = run(args + ["--merge-brands", "--dry-run"])
    assert "[new copy] Overture 3D PLA @X → Overture PLA @X" in text and "[rename] Overture 3D PETG @X → Overture PETG @X" in text
    assert "Dry run" in text and (split_brands / "Overture 3D PETG @X.json").exists()
    code, text = run(args + ["--merge-brands"], answers=["n"])
    assert code == 1 and "Cancelled" in text
    checklist = tmp_path / "old.md"
    code, text = run(args + ["--merge-brands", "--yes", "--list-file", str(checklist)])
    assert code == 0 and "1 renamed, 0 updated, 1 copied, 0 skipped" in text and "Backup" in text
    assert "Delete these old profiles in Bambu Studio" in text and "- [ ] Overture 3D PLA @X (cloud" in checklist.read_text(encoding="utf-8")
    assert (split_brands / "Overture PETG @X.json").exists() and not (split_brands / "Overture 3D PETG @X.json").exists()
    code, text = run(args + ["--merge-brands", "--vendor", "acme"])
    assert code == 0 and "All brands are spelled the same way" in text


def test_cleanup_merge_with_only_skips(fake_install, split_brands, not_running):
    for name in ("Overture PLA @X", "Overture PETG @X"):
        (split_brands / f"{name}.json").write_text(json.dumps({"name": name, "inherits": "", "filament_vendor": ["Overture"]}), encoding="utf-8")
    code, text = run(["cleanup", "--data-dir", str(fake_install), "--user", "123", "--merge-brands"])
    assert code == 0 and text.count("[skip]") == 2 and "Nothing to do" in text
