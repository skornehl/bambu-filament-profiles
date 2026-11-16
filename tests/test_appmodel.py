import json

import pytest

from bambu_filament_profiles.appmodel import AppSession, details, load_catalog, parse_sources, search
from bambu_filament_profiles.catalog import build, write_output
from bambu_filament_profiles.install import InstallError, Installation

from .conftest import PRINTER


@pytest.fixture
def profiles_dir(tmp_path, records, bambu):
    out = tmp_path / "profiles"
    write_output(build(records, bambu, PRINTER), out, {}, PRINTER)
    return out


@pytest.fixture
def session(profiles_dir, fake_install, tmp_path):
    filament = fake_install / "user" / "123" / "filament"
    (filament / "Old PLA.json").write_text(json.dumps({"inherits": "Generic PLA"}), encoding="utf-8")
    (filament / "Cloud PETG.json").write_text(json.dumps({"inherits": "Generic PETG", "compatible_printers": ["Bambu Lab H2D 0.4 nozzle"]}), encoding="utf-8")
    (filament / "Cloud PETG.info").write_text("setting_id = PFUS1\n", encoding="utf-8")
    return AppSession(profiles_dir, tmp_path / "backups", data_dir=str(fake_install), running=lambda: False)


def test_parse_sources():
    assert parse_sources("x: Geeetech PLA. Base Generic PLA. Values from: Open Filament Database, SpoolmanDB.") == ["Open Filament Database", "SpoolmanDB"]
    assert parse_sources("Values from: base profile only.") == []
    assert parse_sources("no sources") == []


def test_catalog_search(profiles_dir):
    items = load_catalog(profiles_dir)
    assert search(items, "geeetech pla")[0].brand == "Geeetech"
    assert {i.brand for i in search(items, brand="geeetech")} == {"Geeetech"}
    assert all(i.material == "PLA" for i in search(items, material="pla"))
    assert search(items, "nothing") == []


def test_details_marks_inherited(profiles_dir, bambu):
    item = next(i for i in load_catalog(profiles_dir) if i.brand == "Geeetech" and i.product == "PLA")
    d = details(item, bambu)
    rows = {r["label"]: r for r in d["rows"]}
    assert rows["Nozzle"]["value"] == "205" and rows["Nozzle"]["origin"] == "source"
    assert rows["Flow ratio"]["origin"] == "inherited" and rows["Flow ratio"]["value"] == "0.98"
    assert d["parent"] == "Generic PLA"
    assert all(r["origin"] == "source" for r in details(item, None)["rows"])


def test_session_state_and_selection(session, fake_install):
    state = session.state()
    assert state["user"] == "123" and state["active_user"] == "123" and state["system_version"] == "02.09.00.81"
    assert state["users"] == ["123", "default"] and not state["running"]
    session.select(user="default")
    assert session.user == "default"
    with pytest.raises(InstallError):
        session.select(user="999")
    with pytest.raises(InstallError):
        session.select(installation=5)


def test_session_without_installation(profiles_dir, tmp_path):
    session = AppSession(profiles_dir, tmp_path / "bk", installations=[])
    state = session.state()
    assert state["data_dir"] is None and state["users"] == []
    assert session.existing() == {"total": 0, "presets": [], "problems": []}
    assert not any(p["installed"] for p in session.profiles())
    with pytest.raises(InstallError, match="no Bambu Studio"):
        session.plan([0])


def test_session_without_system_profiles(profiles_dir, tmp_path):
    data = tmp_path / "empty"
    (data / "user" / "default").mkdir(parents=True)
    session = AppSession(profiles_dir, tmp_path / "bk", installations=[Installation("linux", data)], running=lambda: False)
    assert session.system is None and session.user == "default"
    with pytest.raises(InstallError, match="system profiles"):
        session.plan([0])
    with pytest.raises(InstallError, match="system profiles"):
        session.install([0])


def test_plan_install_and_installed_flag(session, tmp_path):
    item = next(i for i in session.catalog if i.brand == "Geeetech" and i.product == "PLA")
    plan = session.plan([item.id])
    assert plan["actions"] == [{"name": item.name, "kind": "new"}]
    result = session.install([item.id])
    assert result["installed"] == [item.name] and result["backup"]
    assert next(p for p in session.profiles() if p["id"] == item.id)["installed"]
    assert session.install([item.id])["installed"] == []  # unchanged
    with pytest.raises(InstallError):
        session.plan([])
    with pytest.raises(InstallError):
        session.plan([99999])
    with pytest.raises(InstallError):
        session.profile(99999)
    assert session.profile(item.id)["brand"] == "Geeetech"


def test_install_conflicts_need_explicit_overwrite(session):
    item = next(i for i in session.catalog if i.brand == "Geeetech" and i.product == "PLA")
    target = session.filament_dir / "base" / f"{item.name}.json"
    target.write_text(json.dumps({"inherits": "", "filament_id": "Pmine00"}), encoding="utf-8")
    result = session.install([item.id])
    assert result["skipped"] == [item.name] and result["installed"] == [] and result["backup"] is None
    result = session.install([item.id], overwrite=[item.name])
    assert result["installed"] == [item.name]
    assert json.loads(target.read_text(encoding="utf-8"))["filament_id"] == "Pmine00"


def test_writes_refused_while_bambu_runs(session):
    session._running = lambda: True
    with pytest.raises(InstallError, match="running"):
        session.install([0])
    with pytest.raises(InstallError, match="running"):
        session.delete_local(["Old PLA"])


def test_existing_delete_and_checklist(session):
    data = session.existing()
    assert data["total"] == 2
    by_name = {p["name"]: p for p in data["presets"]}
    assert by_name["Cloud PETG"]["cloud"] and by_name["Old PLA"]["vendor"] == "Generic"
    assert [p["name"] for p in session.existing(not_for="P1S")["presets"]] == ["Cloud PETG"]
    assert [p["name"] for p in session.existing(text="old")["presets"]] == ["Old PLA"]
    assert "- [ ] Cloud PETG (cloud" in session.checklist(["Cloud PETG"])
    result = session.delete_local(["Old PLA", "Cloud PETG"])
    assert result["deleted"] == ["Old PLA"] and result["refused"] == ["Cloud PETG"] and result["backup"]
    assert session.delete_local(["Cloud PETG"]) == {"deleted": [], "refused": ["Cloud PETG"], "backup": None}


def test_update_reloads_catalog(profiles_dir, tmp_path, records, bambu):
    calls = []

    def updater(log):
        log("fetched")
        calls.append(1)
        write_output(build(records, bambu, PRINTER), profiles_dir, {}, PRINTER)

    session = AppSession(profiles_dir, tmp_path / "bk", installations=[], updater=updater)
    state = session.state()
    assert state["can_update"] and state["catalog_built"]
    result = session.update()
    assert calls == [1] and result["log"] == ["fetched"] and result["catalog_size"] == len(session.catalog) > 0
    (profiles_dir / "BUILD.json").unlink()
    without = AppSession(profiles_dir, tmp_path / "bk", installations=[])
    assert not without.state()["can_update"] and without.state()["catalog_built"] is None
    with pytest.raises(InstallError, match="not available"):
        without.update()
