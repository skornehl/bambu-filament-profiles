import json

import pytest

from bambu_filament_profiles.sources import cura, manual, ofd, orca, prusa, spoolman, to_number
from bambu_filament_profiles.sources.bambu import BambuProfiles

from .conftest import FIXTURES, PRINTER


@pytest.mark.parametrize(
    "raw, expected",
    [("220", 220.0), (220, 220.0), (["0.98"], 0.98), ("95%", 95.0), ("nil", None), ([], None), (None, None), (True, None), ("abc", None), ("", None)],
)
def test_to_number(raw, expected):
    assert to_number(raw) == expected


def test_bambu_flatten_and_version(bambu):
    flat = bambu.flatten("Generic PLA")
    assert flat["filament_id"] == "GFL99"
    assert flat["filament_type"] == ["PLA"]
    assert flat["name"] == "Generic PLA"
    assert bambu.version == "2.9.0.74"
    assert bambu.resolve("Generic PLA", "filament_vendor") == ["Generic"]
    assert bambu.resolve("does not exist", "x") is None
    with pytest.raises(KeyError):
        bambu.flatten("does not exist")


def test_bambu_compatibility(bambu):
    assert bambu.is_compatible("Generic PLA", PRINTER)
    assert not bambu.is_compatible("Generic PLA", "Bambu Lab A1 0.4 nozzle")
    assert not bambu.is_compatible("Generic PLA @base", PRINTER)  # not instantiable
    keys = bambu.system_keys(PRINTER)
    assert ("overture", "PLA", frozenset()) in keys


def test_bambu_version_fallbacks(tmp_path):
    folder = tmp_path / "resources" / "profiles" / "BBL" / "filament"
    folder.mkdir(parents=True)
    (folder / "x.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    (folder / "broken.json").write_text("{", encoding="utf-8")
    profiles = BambuProfiles(tmp_path)
    assert profiles.version == "2.0.0.0"
    profiles.bundle_version = "1.2"
    assert profiles.version == "1.2.0.0"
    profiles.bundle_version = "a.b"
    assert profiles.version == "0.0.0.0"


def test_bambu_missing_profiles(tmp_path):
    with pytest.raises(FileNotFoundError):
        BambuProfiles(tmp_path)


def test_bambu_from_installation(fake_install):
    profiles = BambuProfiles.from_installation(fake_install)
    assert profiles.bundle_version == "02.09.00.81"
    assert "Generic PLA" in profiles.presets


def test_orca_loader_takes_vendor_layer_only():
    records = orca.load(FIXTURES / "orca", PRINTER)
    assert [r.ref for r in records] == ["Elegoo PLA @System"]
    rec = records[0]
    assert rec.brand == "Elegoo" and rec.material == "PLA" and rec.name == "PLA"
    assert "filament_max_volumetric_speed" in rec.values
    assert rec.diameter == 1.75


def test_orca_variant_choice():
    chain_generic = [{"name": "a", "compatible_printers": []}]
    chain_p1s = [{"name": "b", "compatible_printers": [PRINTER]}]
    chain_a1 = [{"name": "c", "compatible_printers": ["Bambu Lab A1 0.4 nozzle"]}]
    assert orca._choose_variant([(chain_generic[0], chain_generic), (chain_p1s[0], chain_p1s)], PRINTER)[0]["name"] == "b"
    assert orca._choose_variant([(chain_generic[0], chain_generic)], PRINTER)[0]["name"] == "a"
    assert orca._choose_variant([(chain_a1[0], chain_a1)], PRINTER) is None


def test_ofd_loader():
    records = {r.ref: r for r in ofd.load(FIXTURES / "ofd")}
    geeetech = records["geeetech/PLA/pla"]
    assert geeetech.brand == "Geeetech" and geeetech.material == "PLA"
    assert geeetech.values["nozzle_temperature_range_low"] == 185
    assert geeetech.values["_bed_max"] == 60
    assert geeetech.diameter == 1.75
    elegoo = records["elegoo/PLA/pla"]
    assert "Elegoo PLA" in elegoo.links
    peek = records["tectonic_3d/PEEK/cf_peek"]
    assert peek.values["nozzle_temperature_range_low"] == 360
    assert peek.diameter is None


def test_ofd_diameter_and_slicer_settings(tmp_path):
    folder = tmp_path / "data" / "acme" / "PLA" / "x"
    (folder / "red").mkdir(parents=True)
    (tmp_path / "data" / "acme" / "brand.json").write_text(json.dumps({"name": "ACME"}), encoding="utf-8")
    (folder / "filament.json").write_text(
        json.dumps({"name": "X", "slicer_settings": {"generic": {"nozzle_temp": 210, "first_layer_bed_temp": 65}, "bambustudio": {"profile_name": "ACME X"}}}),
        encoding="utf-8",
    )
    (folder / "red" / "sizes.json").write_text(json.dumps([{"diameter": 2.85}]), encoding="utf-8")
    (tmp_path / "data" / "nobrand").mkdir()
    (record,) = ofd.load(tmp_path)
    assert record.material == "PLA"
    assert record.values == {"nozzle_temperature": 210, "_bed_first": 65}
    assert record.diameter == 2.85
    assert record.links == {"ACME X"}


def test_prusa_loader_and_inheritance():
    records = prusa.load(FIXTURES / "prusa")
    assert [r.ref for r in records] == ["Fillamentum PLA"]
    rec = records[0]
    assert rec.brand == "Fillamentum" and rec.material == "PLA" and rec.name == "PLA"
    assert rec.values["filament_density"] == 1.24
    assert rec.values["nozzle_temperature"] > 0
    assert "filament_max_volumetric_speed" not in rec.values


def test_prusa_ini_details(tmp_path):
    text = "[filament:*a*]\ntemperature = 200\ncooling = 1\nmin_fan_speed = 50\nmax_fan_speed = 90\n\n# Kommentar\n[filament:Acme X]\ninherits = *a*\nfilament_vendor = Acme\nfilament_type = PETG\n[print:egal]\nfoo = bar\n"
    sections = {n: v for (k, n), v in prusa.parse_ini(text).items() if k == "filament"}
    assert prusa.resolve_sections(sections, "Acme X")["temperature"] == "200"
    assert prusa.resolve_sections(sections, "missing") == {}
    (tmp_path / "live" / "Templates").mkdir(parents=True)
    (tmp_path / "live" / "Templates" / "1.0.2.ini").write_text("", encoding="utf-8")
    (tmp_path / "live" / "Templates" / "1.0.10.ini").write_text(text, encoding="utf-8")
    assert prusa.latest_bundle(tmp_path).name == "1.0.10.ini"
    (rec,) = prusa.load(tmp_path)
    assert rec.values == {"nozzle_temperature": 200, "fan_min_speed": 50, "fan_max_speed": 90}
    assert prusa.load(tmp_path / "empty") == []


def test_spoolman_loader():
    records = spoolman.load(FIXTURES / "spoolman")
    names = {r.name for r in records}
    assert "PLA" in names  # "{color_name}" alone becomes the material
    assert "Luminous" in names
    plain = next(r for r in records if r.name == "PLA")
    assert plain.values["nozzle_temperature"] == 205
    assert plain.values["_bed"] == 60
    luminous = next(r for r in records if r.name == "Luminous")
    assert luminous.values["nozzle_temperature_range_low"] == 190
    assert luminous.values["_bed_min"] == 50


def test_cura_loader(tmp_path):
    (rec,) = cura.load(FIXTURES / "cura")
    assert rec.brand == "eSUN" and rec.name == "PLA+"
    assert rec.values == {"filament_density": 1.24, "nozzle_temperature": 210.0, "_bed": 60.0}
    (tmp_path / "bad.xml.fdm_material").write_text("<broken", encoding="utf-8")
    assert cura.load(tmp_path) == []


def test_manual_loader(tmp_path):
    assert manual.load(tmp_path / "missing") == []
    (tmp_path / "a.toml").write_text('brand = "Geeetech"\nmaterial = "PLA"\nname = "PLA"\n[values]\nfilament_flow_ratio = 0.98\n', encoding="utf-8")
    (rec,) = manual.load(tmp_path)
    assert rec.source == "manual" and rec.values == {"filament_flow_ratio": 0.98}


@pytest.mark.parametrize(
    "content, message",
    [
        ('brand = "X"\nmaterial = "PLA"\n', "missing name"),
        ('brand = "X"\nmaterial = "PLA"\nname = "Y"\n[values]\nfoo = 1\n', "unknown key"),
        ('brand = "X"\nmaterial = "PLA"\nname = "Y"\n[values]\nnozzle_temperature = "hot"\n', "not a number"),
    ],
)
def test_manual_errors(tmp_path, content, message):
    (tmp_path / "bad.toml").write_text(content, encoding="utf-8")
    with pytest.raises(manual.ManualError, match=message):
        manual.load(tmp_path)


def test_broken_upstream_files_are_skipped_and_reported(tmp_path):
    import shutil

    for name in ("orca", "ofd", "spoolman"):
        shutil.copytree(FIXTURES / name, tmp_path / name)
    (tmp_path / "orca" / "resources" / "profiles" / "OrcaFilamentLibrary" / "filament" / "broken.json").write_text("{", encoding="utf-8")
    (tmp_path / "ofd" / "data" / "geeetech" / "PLA" / "pla" / "filament.json").write_text("[1]", encoding="utf-8")
    (tmp_path / "spoolman" / "filaments" / "broken.json").write_text("{", encoding="utf-8")

    problems: list[str] = []
    assert [r.ref for r in orca.load(tmp_path / "orca", PRINTER, problems)] == ["Elegoo PLA @System"]
    assert ofd.load(tmp_path / "ofd", problems) and spoolman.load(tmp_path / "spoolman", problems)
    assert [p.split(":")[0] for p in problems] == ["broken.json", "filament.json", "broken.json"]
    assert ofd.load(tmp_path / "nothing") == []


def test_ofd_broken_brand_and_material_files(tmp_path):
    material = tmp_path / "data" / "acme" / "PLA"
    (material / "matte").mkdir(parents=True)
    (tmp_path / "data" / "acme" / "brand.json").write_text('{"name": "Acme"}', encoding="utf-8")
    (material / "material.json").write_text("{", encoding="utf-8")
    (material / "matte" / "filament.json").write_text('{"name": "Matte PLA"}', encoding="utf-8")
    broken_brand = tmp_path / "data" / "other"
    broken_brand.mkdir()
    (broken_brand / "brand.json").write_text("{", encoding="utf-8")
    problems: list[str] = []
    (record,) = ofd.load(tmp_path, problems)
    assert record.brand == "Acme" and record.material == "PLA"  # folder name as fallback
    assert sorted(p.split(":")[0] for p in problems) == ["brand.json", "material.json"]


def test_spoolman_ignores_incomplete_ranges(tmp_path):
    folder = tmp_path / "filaments"
    folder.mkdir()
    item = {"name": "PLA", "material": "PLA", "extruder_temp_range": [None, 220], "bed_temp_range": ["x", 60], "diameters": [1.75]}
    (folder / "acme.json").write_text(json.dumps({"manufacturer": "Acme", "filaments": [item]}), encoding="utf-8")
    (record,) = spoolman.load(tmp_path)
    assert record.values == {}


def test_bambu_vendors(bambu):
    assert bambu.vendors() == {"Overture"}  # without "Generic"
