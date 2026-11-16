import json

from bambu_filament_profiles.catalog import build, list_profiles, load_records, select_profiles, write_output

from .conftest import FIXTURES, PRINTER

LOCK = {"ofd": {"commit": "abcdef1234567890", "license": "MIT"}}


def test_load_records_reports_missing_sources(tmp_path):
    lines = []
    records = load_records(tmp_path, tmp_path / "manual", PRINTER, log=lines.append)
    assert records == {"manual": []}
    assert len(lines) == 5


def test_build_and_write(tmp_path, records, bambu):
    result = build(records, bambu, PRINTER)
    names = {g.alias for g in result.ok}
    assert {"Geeetech PLA", "ELEGOO PLA", "Fillamentum PLA", "eSUN PLA+"} <= names
    assert "Overture PLA" not in names
    assert result.counts["ok"] == len(result.ok)
    write_output(result, tmp_path / "profiles", LOCK, PRINTER)
    spec = json.loads((tmp_path / "profiles" / "Geeetech" / "PLA" / "PLA.json").read_text(encoding="utf-8"))
    assert spec["inherits"] == "Generic PLA"
    index = (tmp_path / "profiles" / "INDEX.md").read_text(encoding="utf-8")
    assert "## Geeetech" in index and "abcdef123456" in index
    report = (tmp_path / "profiles" / "REPORT.md").read_text(encoding="utf-8")
    assert "PEEK" in report and "Systemprofil" in report


def test_write_output_replaces_old_files(tmp_path, records, bambu):
    out = tmp_path / "profiles"
    (out / "Alt" / "PLA").mkdir(parents=True)
    (out / "Alt" / "PLA" / "x.json").write_text("{}", encoding="utf-8")
    (out / "notiz.txt").write_text("bleibt", encoding="utf-8")
    write_output(build(records, bambu, PRINTER), out, LOCK, PRINTER)
    assert not (out / "Alt").exists()
    assert (out / "notiz.txt").exists()


def test_duplicate_paths_get_suffix(bambu):
    from bambu_filament_profiles.catalog import _dedupe_paths
    from bambu_filament_profiles.generate import generate
    from bambu_filament_profiles.model import Entry, Record

    def entry(name):
        e = Entry(brand="Acme", family="PLA", name=name, tokens=frozenset({name}), material="PLA")
        e.records.append(Record(source="ofd", brand="Acme", material="PLA", name=name, ref=name))
        return e

    first, second, third = (generate(entry("PLA Rot"), bambu, PRINTER) for _ in range(3))
    _dedupe_paths([first, second, third])
    assert first.relpath == "Acme/PLA/PLA Rot.json"
    assert second.relpath == "Acme/PLA/PLA Rot (2).json"
    assert third.profile["name"] == f"Acme PLA Rot (3) @{PRINTER}"


def test_duplicate_names_in_different_folders(bambu):
    from bambu_filament_profiles.catalog import _dedupe_paths
    from bambu_filament_profiles.generate import generate
    from bambu_filament_profiles.model import Entry, Record

    def entry():
        e = Entry(brand="Acme", family="PLA", name="BVOH", tokens=frozenset(), material="PLA")
        e.records.append(Record(source="ofd", brand="Acme", material="PLA", name="BVOH", ref="x"))
        return e

    a, b = generate(entry(), bambu, PRINTER), generate(entry(), bambu, PRINTER)
    b.family = "BVOH"  # anderer Ordner, gleicher Profilname
    _dedupe_paths([a, b])
    assert a.name == f"Acme BVOH @{PRINTER}"
    assert b.name == f"Acme BVOH (2) @{PRINTER}" and b.profile["name"] == b.name


def test_list_and_select(tmp_path, records, bambu):
    write_output(build(records, bambu, PRINTER), tmp_path, LOCK, PRINTER)
    items = list_profiles(tmp_path)
    assert {i["brand"] for i in items} >= {"Geeetech", "Fillamentum"}
    assert {i["brand"] for i in select_profiles(items, vendors=["geee"])} == {"Geeetech"}
    assert select_profiles(items, materials=["peek"]) == []  # PEEK ist für den P1S zu heiß
    assert len(select_profiles(items, materials=["pla"], names=["pla"])) == len([i for i in items if i["material"] == "PLA"])


def test_report_lists_unmatched(tmp_path, bambu):
    from bambu_filament_profiles.model import Record

    records = {"spoolman": [Record(source="spoolman", brand="X", material="Holz", name="Holz", ref="r")]}
    result = build(records, bambu, PRINTER)
    write_output(result, tmp_path, {}, PRINTER)
    assert "Nicht zugeordnet" in (tmp_path / "REPORT.md").read_text(encoding="utf-8")


def test_fixture_sources_exist():
    for name in ("bambu", "orca", "ofd", "prusa", "spoolman", "cura"):
        assert (FIXTURES / name).is_dir()
