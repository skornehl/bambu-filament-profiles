import json
import shutil
from pathlib import Path

import pytest

from bambu_filament_profiles.catalog import load_records
from bambu_filament_profiles.sources.bambu import BambuProfiles

FIXTURES = Path(__file__).parent / "fixtures"
PRINTER = "Bambu Lab P1S 0.4 nozzle"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Tests sehen nie das echte Home (keine echte Bambu-Studio-Installation, keine Backups dort)."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(home / var.lower()))
    return home


@pytest.fixture
def bambu():
    return BambuProfiles(FIXTURES / "bambu")


@pytest.fixture
def records():
    return load_records(FIXTURES, None, PRINTER, log=lambda *a: None)


@pytest.fixture
def fake_install(tmp_path):
    """Bambu-Studio-Datenordner mit Systemprofilen aus den Fixtures und Benutzer 123."""
    data = tmp_path / "BambuStudio"
    shutil.copytree(FIXTURES / "bambu" / "resources" / "profiles" / "BBL" / "filament", data / "system" / "BBL" / "filament")
    (data / "system" / "BBL.json").write_text(json.dumps({"name": "Bambu Lab", "version": "02.09.00.81"}), encoding="utf-8")
    (data / "user" / "123" / "filament" / "base").mkdir(parents=True)
    (data / "user" / "default" / "filament").mkdir(parents=True)
    (data / "BambuStudio.conf").write_text(json.dumps({"app": {"preset_folder": "123"}}), encoding="utf-8")
    return data
