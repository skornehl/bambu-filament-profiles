import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from bambu_filament_profiles import MARKER
from bambu_filament_profiles.install import (
    Action,
    InstallError,
    Installation,
    UserPreset,
    active_user,
    assign_filament_id,
    backup,
    bambu_running,
    candidate_dirs,
    choose_installation,
    choose_user,
    default_data_dir,
    delete_local,
    filter_presets,
    find_installations,
    plan_install,
    read_info,
    scan_user_presets,
    user_ids,
    write_profile,
)
from bambu_filament_profiles.sources.bambu import BambuProfiles


# ------------------------------------------------------------------ Pfadsuche


def test_candidate_dirs_linux(tmp_path):
    dirs = candidate_dirs("linux", {}, tmp_path)
    assert [d.kind for d in dirs] == ["linux", "flatpak"]
    assert dirs[0].data_dir == tmp_path / ".config" / "BambuStudio"
    assert dirs[1].data_dir == tmp_path / ".var" / "app" / "com.bambulab.BambuStudio" / "config" / "BambuStudio"
    xdg = candidate_dirs("linux", {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}, tmp_path)
    assert xdg[0].data_dir == tmp_path / "xdg" / "BambuStudio"


def test_candidate_dirs_windows_and_macos(tmp_path):
    win = candidate_dirs("win32", {"APPDATA": str(tmp_path / "Roaming")}, tmp_path)
    assert win == [Installation("windows", tmp_path / "Roaming" / "BambuStudio")]
    win_fallback = candidate_dirs("win32", {}, tmp_path)
    assert win_fallback[0].data_dir == tmp_path / "AppData" / "Roaming" / "BambuStudio"
    mac = candidate_dirs("darwin", {}, tmp_path)
    assert mac[0].data_dir == tmp_path / "Library" / "Application Support" / "BambuStudio"


def test_find_installations_simulated_linux(tmp_path):
    flatpak = tmp_path / ".var" / "app" / "com.bambulab.BambuStudio" / "config" / "BambuStudio"
    (flatpak / "user").mkdir(parents=True)
    (tmp_path / ".config" / "BambuStudio").mkdir(parents=True)  # empty → no installation
    found = find_installations("linux", {}, tmp_path)
    assert [i.kind for i in found] == ["flatpak"]
    (tmp_path / ".config" / "BambuStudio" / "BambuStudio.conf").write_text("{}", encoding="utf-8")
    assert [i.kind for i in find_installations("linux", {}, tmp_path)] == ["linux", "flatpak"]


def test_find_installations_simulated_windows(tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    (appdata / "BambuStudio").mkdir(parents=True)
    (appdata / "BambuStudio" / "BambuStudio.conf").write_text("{}", encoding="utf-8")
    found = find_installations("win32", {"APPDATA": str(appdata)}, tmp_path)
    assert found == [Installation("windows", appdata / "BambuStudio")]
    assert str(found[0]) == f"windows: {appdata / 'BambuStudio'}"


def test_active_user_and_user_ids(fake_install, tmp_path):
    assert active_user(fake_install) == "123"
    assert user_ids(fake_install) == ["123", "default"]
    assert active_user(tmp_path / "missing") is None
    (tmp_path / "BambuStudio.conf").write_text("[]", encoding="utf-8")
    assert active_user(tmp_path) is None
    assert user_ids(tmp_path / "missing") == []


def test_choose_installation(tmp_path):
    a, b = Installation("linux", tmp_path / "a"), Installation("flatpak", tmp_path / "b")
    assert choose_installation([a], None, None) == a
    assert choose_installation([a, b], None, lambda q: "2") == b
    assert choose_installation([a, b], None, lambda q: "") == a
    with pytest.raises(InstallError, match="with an option"):
        choose_installation([a, b], None, None)
    with pytest.raises(InstallError, match="invalid choice"):
        choose_installation([a, b], None, lambda q: "9")
    with pytest.raises(InstallError, match="no Bambu Studio"):
        choose_installation([], None, None)
    assert choose_installation([], str(tmp_path), None).data_dir == tmp_path
    with pytest.raises(InstallError, match="does not exist"):
        choose_installation([], str(tmp_path / "missing"), None)


def test_choose_user(fake_install, tmp_path):
    questions = []

    def ask(q):
        questions.append(q)
        return ""

    assert choose_user(fake_install, None, ask) == "123"  # active user first
    assert "active: 123" in questions[0]
    assert choose_user(fake_install, "default", None) == "default"
    with pytest.raises(InstallError, match="does not exist"):
        choose_user(fake_install, "999", None)
    with pytest.raises(InstallError):
        choose_user(fake_install, None, None)
    single = tmp_path / "single"
    (single / "user" / "default").mkdir(parents=True)
    assert choose_user(single, None, None) == "default"
    assert choose_user(tmp_path / "empty", None, None) == "default"


# ------------------------------------------------------------------- processes


def test_bambu_running_linux(tmp_path):
    for pid, comm in (("1", "systemd"), ("42", "bambu-studio"), ("self", "x")):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "comm").write_text(comm + "\n", encoding="utf-8")
    (tmp_path / "7").mkdir()  # without comm
    assert bambu_running("linux", tmp_path)
    (tmp_path / "42" / "comm").write_text("bash\n", encoding="utf-8")
    assert not bambu_running("linux", tmp_path)
    assert not bambu_running("linux", tmp_path / "missing")


def test_bambu_running_windows_and_macos():
    def fake(out="", code=0, error=False):
        def run(*args, **kwargs):
            if error:
                raise OSError("missing")
            return subprocess.CompletedProcess(args, code, stdout=out)

        return run

    assert bambu_running("win32", run=fake('"bambu-studio.exe","123"'))
    assert not bambu_running("win32", run=fake('"explorer.exe","1"'))
    assert not bambu_running("win32", run=fake(error=True))
    assert bambu_running("darwin", run=fake(code=0))
    assert not bambu_running("darwin", run=fake(code=1))
    assert not bambu_running("darwin", run=fake(error=True))


# ------------------------------------------------------- existing profiles


def write_preset(folder: Path, name: str, data: dict, setting_id: str | None = None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"name": name, **data}), encoding="utf-8")
    if setting_id is not None:
        (folder / f"{name}.info").write_text(f"sync_info = \nsetting_id = {setting_id}\n", encoding="utf-8")


@pytest.fixture
def presets_dir(fake_install):
    filament = fake_install / "user" / "123" / "filament"
    write_preset(filament, "SUNLU PLA", {"inherits": "Generic PLA", "filament_vendor": ["SUNLU"]}, "PFUS1")
    write_preset(filament, "My PETG", {"inherits": "Generic PETG"})
    write_preset(filament, "Tinmorry Silk", {"inherits": "Bambu PLA Silk"}, "null")
    write_preset(filament / "base", "eSUN PETG Basic @Bambu Lab P1S 0.4 nozzle", {"inherits": "", "filament_vendor": ["eSUN"], "filament_id": "P18f7b94"}, "PFUS2")
    write_preset(filament / "base", "Acme PLA @Bambu Lab P1S 0.4 nozzle", {"inherits": "", "filament_vendor": ["Acme"], "filament_id": "Pabc1234", "description": MARKER + " 0.1.0"})
    (filament / "broken.json").write_text("{", encoding="utf-8")
    return filament


def test_scan_user_presets(presets_dir):
    presets, problems = scan_user_presets(presets_dir)
    by_name = {p.name: p for p in presets}
    assert len(presets) == 5 and problems and "broken.json" in problems[0]
    assert by_name["SUNLU PLA"].synced and by_name["SUNLU PLA"].shown_vendor == "Generic"
    assert by_name["SUNLU PLA"].kind == "inherits Generic PLA"
    assert not by_name["Tinmorry Silk"].synced  # setting_id = null
    assert by_name["Tinmorry Silk"].shown_vendor == "as Bambu PLA Silk"
    esun = by_name["eSUN PETG Basic @Bambu Lab P1S 0.4 nozzle"]
    assert esun.root and esun.shown_vendor == "eSUN" and esun.kind == "standalone"
    assert by_name["Acme PLA @Bambu Lab P1S 0.4 nozzle"].from_tool
    assert scan_user_presets(presets_dir / "missing") == ([], [])


def test_filter_presets(presets_dir):
    presets, _ = scan_user_presets(presets_dir)
    names = lambda items: sorted(p.name for p in items)  # noqa: E731
    assert names(filter_presets(presets, generic_only=True)) == ["My PETG", "SUNLU PLA"]
    assert names(filter_presets(presets, vendors=["esun"])) == ["eSUN PETG Basic @Bambu Lab P1S 0.4 nozzle"]
    assert names(filter_presets(presets, names=["petg"])) == ["My PETG", "eSUN PETG Basic @Bambu Lab P1S 0.4 nozzle"]
    assert names(filter_presets(presets, tool_only=True)) == ["Acme PLA @Bambu Lab P1S 0.4 nozzle"]


def test_read_info_missing(tmp_path):
    assert read_info(tmp_path / "missing.info") == {}


def test_shown_vendor_root_without_vendor(tmp_path):
    preset = UserPreset("x", tmp_path / "x.json", True, "", "", "", "", False)
    assert preset.shown_vendor == "?"


# ----------------------------------------------------------------- installation


def spec_file(tmp_path: Path, name="Acme PLA @Bambu Lab P1S 0.4 nozzle", **values) -> Path:
    spec = {
        "name": name,
        "from": "User",
        "inherits": "Generic PLA",
        "version": "2.9.0.74",
        "description": MARKER + " 0.1.0",
        "filament_settings_id": [name],
        "filament_vendor": ["Acme"],
        "compatible_printers": ["Bambu Lab P1S 0.4 nozzle"],
        **{k: [str(v)] for k, v in values.items()},
    }
    path = tmp_path / f"{len(list(tmp_path.glob('*.json')))}.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_assign_filament_id(presets_dir):
    presets, _ = scan_user_presets(presets_dir)
    assert assign_filament_id("Acme PLA @Bambu Lab P1S 0.6 nozzle", "123", presets) == "Pabc1234"  # same name
    new = assign_filament_id("New PLA @X", "123", presets)
    assert new.startswith("P") and new not in {"Pabc1234", "P18f7b94"}
    assert assign_filament_id("New PLA @X", "default", presets) != new  # without account ID


def test_assign_filament_id_avoids_collision(tmp_path):
    from bambu_filament_profiles.generate import filament_id_for

    taken = UserPreset("Fremd @X", tmp_path, True, "", "", filament_id_for("Neu", "1"), "", False)
    assert assign_filament_id("Neu @X", "1", [taken]) != taken.filament_id


def test_plan_and_write_install(fake_install, presets_dir, tmp_path):
    system = BambuProfiles.from_installation(fake_install)
    presets, _ = scan_user_presets(presets_dir)
    specs = tmp_path / "specs"
    specs.mkdir()
    new_spec = spec_file(specs, "Neu PLA @Bambu Lab P1S 0.4 nozzle", nozzle_temperature=205)
    conflict_spec = spec_file(specs, "Acme PLA @Bambu Lab P1S 0.4 nozzle", nozzle_temperature=210)
    bad = specs / "bad.json"
    bad.write_text(json.dumps({"name": "Broken @X", "inherits": "Missing"}), encoding="utf-8")
    actions, errors = plan_install([new_spec, conflict_spec, bad], presets_dir, presets, system, "123")
    assert [a.kind for a in actions] == ["new", "conflict"] and "Broken" in errors[0]
    new = actions[0]
    assert new.target == presets_dir / "base" / "Neu PLA @Bambu Lab P1S 0.4 nozzle.json"
    assert new.data["inherits"] == "" and new.data["version"] == "2.9.0.81"
    write_profile(new, "123", now=1_700_000_000)
    written = json.loads(new.target.read_text(encoding="utf-8"))
    assert written["nozzle_temperature"] == ["205"] and written["filament_vendor"] == ["Acme"]
    info = read_info(new.target.with_suffix(".info"))
    assert info == {"sync_info": "", "user_id": "123", "setting_id": "", "base_id": "", "updated_time": "1700000000"}
    presets, _ = scan_user_presets(presets_dir)
    again, _ = plan_install([new_spec], presets_dir, presets, system, "123")
    assert again[0].kind == "same"


def test_write_profile_default_user(tmp_path):
    action = Action("new", tmp_path / "s.json", tmp_path / "base" / "X.json", "X", {"name": "X"})
    write_profile(action, "default")
    assert read_info(action.target.with_suffix(".info"))["user_id"] == ""


def test_backup_and_delete(presets_dir, tmp_path):
    archive = backup(presets_dir, tmp_path / "backups", "123")
    with zipfile.ZipFile(archive) as z:
        assert "filament/SUNLU PLA.json" in z.namelist()
    assert backup(tmp_path / "missing", tmp_path / "backups", "x").exists()
    presets, _ = scan_user_presets(presets_dir)
    by_name = {p.name: p for p in presets}
    delete_local(by_name["My PETG"])
    assert not (presets_dir / "Mein PETG.json").exists()
    with pytest.raises(InstallError, match="cloud"):
        delete_local(by_name["SUNLU PLA"])
    assert (presets_dir / "SUNLU PLA.json").exists()


def test_default_data_dir(tmp_path):
    assert default_data_dir("linux", {}, tmp_path) == tmp_path / ".local" / "share" / "bambu-filament-profiles"
    assert default_data_dir("linux", {"XDG_DATA_HOME": str(tmp_path / "d")}, tmp_path) == tmp_path / "d" / "bambu-filament-profiles"
    assert default_data_dir("win32", {"LOCALAPPDATA": str(tmp_path / "L")}, tmp_path) == tmp_path / "L" / "bambu-filament-profiles"
    assert default_data_dir("win32", {}, tmp_path) == tmp_path / "AppData" / "Local" / "bambu-filament-profiles"
    assert default_data_dir("darwin", {}, tmp_path) == tmp_path / "Library" / "Application Support" / "bambu-filament-profiles"


def test_printers_and_not_for(fake_install, tmp_path):
    system = BambuProfiles.from_installation(fake_install)
    explicit = UserPreset("A", tmp_path, False, "Generic PLA", "", "", "", False, ("Bambu Lab H2D 0.4 nozzle",))
    root = UserPreset("B @Bambu Lab A1 0.4 nozzle", tmp_path, True, "", "X", "", "", False)
    root_plain = UserPreset("C", tmp_path, True, "", "X", "", "", False)
    inherited = UserPreset("D", tmp_path, False, "Generic PLA", "", "", "", False)
    orphan = UserPreset("E", tmp_path, False, "Missing", "", "", "", False)
    assert explicit.printers() == ["Bambu Lab H2D 0.4 nozzle"]
    assert root.printers() == ["Bambu Lab A1 0.4 nozzle"]
    assert root_plain.printers() == [] and root_plain.usable_on("P1S")
    assert inherited.printers() is None and inherited.usable_on("P1S") is None
    assert "Bambu Lab P1S 0.4 nozzle" in inherited.printers(system) and inherited.usable_on("P1S 0.4", system)
    assert orphan.printers(system) is None
    selected = filter_presets([explicit, root, root_plain, inherited, orphan], not_for="P1S", system=system)
    assert [p.name for p in selected] == ["A", "B @Bambu Lab A1 0.4 nozzle"]


def fake_proc(root: Path, pid: str, comm: str, argv: list[str] | None = None):
    (root / pid).mkdir(parents=True)
    (root / pid / "comm").write_text(comm + "\n", encoding="utf-8")
    if argv is not None:
        (root / pid / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


def test_bambu_running_detects_flatpak_main_thread(tmp_path):
    # This is what Bambu Studio 2.9.1 looks like as a Flatpak: comm of the main thread, program /app/bin/bambu-studio
    fake_proc(tmp_path, "174183", "bambustu_main", ["/app/bin/bambu-studio"])
    assert bambu_running("linux", tmp_path)


def test_bambu_running_detects_program_name(tmp_path):
    fake_proc(tmp_path, "10", "GUI-Thread", ["/app/bin/bambu-studio", "bambustudio://open?file=x"])
    assert bambu_running("linux", tmp_path)
    other = tmp_path / "appimage"
    fake_proc(other, "11", "AppRun", ["/home/u/Apps/Bambu_Studio_linux_ubuntu-v02.09.01.70.AppImage"])
    assert bambu_running("linux", other)


def test_bambu_running_ignores_shells_mentioning_bambu(tmp_path):
    fake_proc(tmp_path, "20", "zsh", ["/usr/bin/zsh", "-c", "pgrep -f /app/bin/bambu-studio"])
    fake_proc(tmp_path, "21", "python3", ["python3", "bfp.py", "install", "--vendor", "bambu-studio"])
    fake_proc(tmp_path, "22", "kworker", [])
    fake_proc(tmp_path, "23", "no-cmdline")
    assert not bambu_running("linux", tmp_path)
