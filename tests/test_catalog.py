import json
from datetime import datetime, timezone

import pytest

from bambu_filament_profiles import catalog
from bambu_filament_profiles.catalog import (
    build,
    catalog_age_days,
    list_profiles,
    load_records,
    read_build_info,
    select_profiles,
    update_profiles,
    write_output,
)

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
    assert "PEEK" in report and "system profile" in report


def test_write_output_replaces_old_files(tmp_path, records, bambu):
    out = tmp_path / "profiles"
    (out / "Old" / "PLA").mkdir(parents=True)
    (out / "Old" / "PLA" / "x.json").write_text("{}", encoding="utf-8")
    (out / "note.txt").write_text("stays", encoding="utf-8")
    (out / ".bambu-filament-profiles").write_text("", encoding="utf-8")
    write_output(build(records, bambu, PRINTER), out, LOCK, PRINTER)
    assert not (out / "Old").exists()
    assert (out / "note.txt").exists()


def test_write_output_refuses_foreign_folder(tmp_path, records, bambu):
    out = tmp_path / "foreign"
    (out / "Photos").mkdir(parents=True)
    (out / "INDEX.md").write_text("my own index", encoding="utf-8")  # a common name is no proof
    with pytest.raises(ValueError, match="not empty"):
        write_output(build(records, bambu, PRINTER), out, LOCK, PRINTER)
    assert (out / "Photos").exists() and (out / "INDEX.md").exists()


def test_catalog_from_v020_is_still_recognised(tmp_path, records, bambu):
    out = tmp_path / "profiles"
    (out / "Old").mkdir(parents=True)
    (out / "BUILD.json").write_text('{"built": "2026-11-16T00:00:00+00:00"}', encoding="utf-8")
    write_output(build(records, bambu, PRINTER), out, LOCK, PRINTER)
    assert not (out / "Old").exists() and (out / ".bambu-filament-profiles").exists()


def test_build_info_and_age(tmp_path, records, bambu):
    out = tmp_path / "profiles"
    then = datetime(2026, 1, 1, 12, 30, 15, 999, tzinfo=timezone.utc)
    write_output(build(records, bambu, PRINTER), out, LOCK, PRINTER, now=then)
    info = read_build_info(out)
    assert info["built"] == "2026-01-01T12:30:15+00:00" and info["printer"] == PRINTER and info["sources"] == LOCK
    assert info["profiles"] == len(list_profiles(out))
    assert catalog_age_days(info, now=datetime(2026, 1, 31, 13, tzinfo=timezone.utc)) == 30
    assert catalog_age_days({"built": "2026-01-01T00:00:00"}, now=datetime(2026, 1, 3, tzinfo=timezone.utc)) == 2
    assert catalog_age_days(None) is None
    (out / "BUILD.json").write_text('{"built": "yesterday"}', encoding="utf-8")
    assert read_build_info(out) is None
    assert read_build_info(tmp_path / "missing") is None


def test_update_profiles_fetches_newest_then_builds(monkeypatch, tmp_path):
    calls = []

    def fake_fetch_all(cache, lock, update, log):
        calls.append((cache, lock, update))
        return {"ofd": {"commit": "f" * 40, "license": "MIT"}}

    monkeypatch.setattr(catalog, "fetch_all", fake_fetch_all)
    lock = tmp_path / "data" / "sources.lock.json"
    out = tmp_path / "data" / "profiles"
    result = update_profiles(FIXTURES, lock, None, out, PRINTER, log=lambda *a: None)
    assert calls == [(FIXTURES, {}, True)] and result.ok
    assert json.loads(lock.read_text(encoding="utf-8"))["ofd"]["commit"] == "f" * 40
    assert read_build_info(out)["sources"]["ofd"]["license"] == "MIT"
    update_profiles(FIXTURES, lock, None, out, PRINTER, pinned=True, log=lambda *a: None)
    assert calls[-1][2] is False and calls[-1][1]["ofd"]["commit"] == "f" * 40


def test_failed_build_keeps_the_last_good_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "fetch_all", lambda cache, lock, update, log: {"ofd": {"commit": "b" * 40}})
    lock = tmp_path / "sources.lock.json"
    lock.write_text('{"ofd": {"commit": "' + "a" * 40 + '"}}', encoding="utf-8")
    with pytest.raises(FileNotFoundError):  # no Bambu profiles in the cache → build fails
        update_profiles(tmp_path / "empty-cache", lock, None, tmp_path / "out", PRINTER, log=lambda *a: None)
    assert json.loads(lock.read_text(encoding="utf-8"))["ofd"]["commit"] == "a" * 40


def test_build_info_lists_sources_per_profile(tmp_path, records, bambu):
    out = tmp_path / "profiles"
    write_output(build(records, bambu, PRINTER), out, LOCK, PRINTER)
    info = read_build_info(out)
    assert info["format"] == catalog.CATALOG_FORMAT
    assert "Open Filament Database" in info["values_from"]["Geeetech/PLA/PLA.json"]


def test_report_counts_error_reasons_by_code(tmp_path, records, bambu):
    write_output(build(records, bambu, PRINTER), tmp_path, LOCK, PRINTER)
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "- too hot for the nozzle:" in report or "- no matching base profile:" in report
    from bambu_filament_profiles.generate import Issue

    assert catalog._reason(Issue("error", "something new", "")) == "something new"


def test_duplicate_paths_get_suffix(bambu):
    from bambu_filament_profiles.catalog import _dedupe_paths
    from bambu_filament_profiles.generate import generate
    from bambu_filament_profiles.model import Entry, Record

    def entry(name):
        e = Entry(brand="Acme", family="PLA", name=name, tokens=frozenset({name}), material="PLA")
        e.records.append(Record(source="ofd", brand="Acme", material="PLA", name=name, ref=name))
        return e

    first, second, third = (generate(entry("PLA Red"), bambu, PRINTER) for _ in range(3))
    _dedupe_paths([first, second, third])
    assert first.relpath == "Acme/PLA/PLA Red.json"
    assert second.relpath == "Acme/PLA/PLA Red (2).json"
    assert third.profile["name"] == f"Acme PLA Red (3) @{PRINTER}"


def test_duplicate_names_in_different_folders(bambu):
    from bambu_filament_profiles.catalog import _dedupe_paths
    from bambu_filament_profiles.generate import generate
    from bambu_filament_profiles.model import Entry, Record

    def entry():
        e = Entry(brand="Acme", family="PLA", name="BVOH", tokens=frozenset(), material="PLA")
        e.records.append(Record(source="ofd", brand="Acme", material="PLA", name="BVOH", ref="x"))
        return e

    a, b = generate(entry(), bambu, PRINTER), generate(entry(), bambu, PRINTER)
    b.family = "BVOH"  # other folder, same profile name
    _dedupe_paths([a, b])
    assert a.name == f"Acme BVOH @{PRINTER}"
    assert b.name == f"Acme BVOH (2) @{PRINTER}" and b.profile["name"] == b.name


def test_list_and_select(tmp_path, records, bambu):
    write_output(build(records, bambu, PRINTER), tmp_path, LOCK, PRINTER)
    items = list_profiles(tmp_path)
    assert {i["brand"] for i in items} >= {"Geeetech", "Fillamentum"}
    assert {i["brand"] for i in select_profiles(items, vendors=["geee"])} == {"Geeetech"}
    assert select_profiles(items, materials=["peek"]) == []  # PEEK is too hot for the P1S
    assert len(select_profiles(items, materials=["pla"], names=["pla"])) == len([i for i in items if i["material"] == "PLA"])


def test_report_lists_unmatched(tmp_path, bambu):
    from bambu_filament_profiles.model import Record

    records = {"spoolman": [Record(source="spoolman", brand="X", material="Holz", name="Holz", ref="r")]}
    result = build(records, bambu, PRINTER)
    write_output(result, tmp_path, {}, PRINTER)
    assert "Unmatched" in (tmp_path / "REPORT.md").read_text(encoding="utf-8")


def test_fixture_sources_exist():
    for name in ("bambu", "orca", "ofd", "prusa", "spoolman", "cura"):
        assert (FIXTURES / name).is_dir()
