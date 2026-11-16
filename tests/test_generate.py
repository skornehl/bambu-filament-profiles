import pytest

from bambu_filament_profiles import MARKER
from bambu_filament_profiles.generate import (
    ExpandError,
    choose_parent,
    expand,
    filament_id_for,
    fmt,
    generate,
    limits_for,
    product_name,
    round5,
)
from bambu_filament_profiles.model import Entry, Record

from .conftest import PRINTER


def make_entry(values=None, family="PLA", name="PLA", brand="Acme", tokens=frozenset(), source="ofd", diameter=None, material=None):
    e = Entry(brand=brand, family=family, name=name, tokens=tokens, material=material or family)
    e.records.append(Record(source=source, brand=brand, material=material or family, name=name, ref="x", values=values or {}, diameter=diameter))
    return e


def messages(result, level):
    return [i.message for i in result.issues if i.level == level]


def test_helpers():
    assert fmt("nozzle_temperature", 212.5) == "213"
    assert fmt("filament_density", 1.24) == "1.24"
    assert fmt("filament_flow_ratio", 1.0) == "1"
    assert round5(202.4) == 200 and round5(202.5) == 205
    assert filament_id_for("Acme PLA") == filament_id_for("Acme PLA")
    assert filament_id_for("Acme PLA").startswith("P") and len(filament_id_for("Acme PLA")) == 8
    assert filament_id_for("Acme PLA", "123") != filament_id_for("Acme PLA")
    assert limits_for(PRINTER).nozzle_max == 300
    assert limits_for("Anderer Drucker").bed_max == 100


def test_product_name():
    assert product_name(make_entry(name="Matte PLA")) == "Matte PLA"
    assert product_name(make_entry(name="Silk")) == "PLA Silk"
    assert product_name(make_entry(name="PLA")) == "PLA"
    assert product_name(make_entry(name="Rot @Spule")) == "PLA Rot  at Spule"


def test_choose_parent(bambu):
    assert choose_parent("PLA", frozenset(), bambu, PRINTER) == "Generic PLA"
    assert choose_parent("PLA", frozenset({"silk"}), bambu, PRINTER) == "Generic PLA Silk"
    assert choose_parent("PET", frozenset(), bambu, PRINTER) == "Generic PETG"
    assert choose_parent("PLA", frozenset({"cf"}), bambu, PRINTER) is None  # CF-Basis fehlt in den Fixtures, kein Rückfall auf PLA
    assert choose_parent("PEEK", frozenset(), bambu, PRINTER) is None


def test_generate_compact_spec(bambu):
    result = generate(make_entry({"nozzle_temperature": 205, "filament_density": 1.25, "_bed": 60}), bambu, PRINTER)
    assert result.ok
    spec = result.profile
    assert spec["name"] == "Acme PLA @" + PRINTER
    assert spec["inherits"] == "Generic PLA" and spec["from"] == "User"
    assert spec["filament_vendor"] == ["Acme"] and spec["compatible_printers"] == [PRINTER]
    assert spec["nozzle_temperature"] == ["205"] and spec["nozzle_temperature_initial_layer"] == ["205"]
    assert spec["textured_plate_temp"] == ["60"] and spec["hot_plate_temp_initial_layer"] == ["60"]
    assert MARKER in spec["description"] and "Open Filament Database" in spec["description"]
    assert not any(k.startswith("_") for k in spec)
    assert result.relpath == "Acme/PLA/PLA.json"


def test_generate_derives_temperatures_from_ranges(bambu):
    result = generate(
        make_entry({"nozzle_temperature_range_low": 185, "nozzle_temperature_range_high": 215, "_bed_min": 25, "_bed_max": 50}),
        bambu,
        PRINTER,
    )
    spec = result.profile
    assert spec["nozzle_temperature"] == ["200"]  # Generic 220 außerhalb → Mitte
    assert result.provenance["nozzle_temperature"] == "derived"
    assert spec["textured_plate_temp"] == ["40"]  # Generic 55 außerhalb 25–50
    assert any("abgeleitet" in m for m in messages(result, "info"))


def test_generate_keeps_inherited_when_inside_range(bambu):
    result = generate(make_entry({"nozzle_temperature_range_low": 190, "nozzle_temperature_range_high": 230, "_bed_min": 50, "_bed_max": 60}), bambu, PRINTER)
    assert "nozzle_temperature" not in result.profile
    assert "textured_plate_temp" not in result.profile


def test_generate_one_sided_ranges(bambu):
    low_only = generate(make_entry({"nozzle_temperature_range_low": 230}), bambu, PRINTER)
    assert low_only.profile["nozzle_temperature"] == ["230"]
    high_only = generate(make_entry({"nozzle_temperature_range_high": 210, "_bed_max": 45}), bambu, PRINTER)
    assert high_only.profile["nozzle_temperature"] == ["210"]
    assert high_only.profile["textured_plate_temp"] == ["45"]


def test_generate_rejects_too_hot(bambu):
    result = generate(make_entry({"nozzle_temperature_range_low": 360, "nozzle_temperature_range_high": 420}), bambu, PRINTER)
    assert not result.ok and "360" in messages(result, "error")[0]
    result = generate(make_entry({"nozzle_temperature": 310}), bambu, PRINTER)
    assert not result.ok
    result = generate(make_entry({"_bed_min": 110, "_bed_max": 120}), bambu, PRINTER)
    assert not result.ok and "Bett" in messages(result, "error")[0]
    result = generate(make_entry({"_bed": 105}), bambu, PRINTER)
    assert not result.ok


def test_generate_clamps_upper_nozzle_bound(bambu):
    result = generate(make_entry({"nozzle_temperature_range_low": 260, "nozzle_temperature_range_high": 320}, family="PETG", name="PETG"), bambu, PRINTER)
    assert result.ok
    assert result.profile["nozzle_temperature_range_high"] == ["300"]
    assert any("begrenzt" in m for m in messages(result, "warning"))


def test_generate_drops_implausible_values(bambu):
    result = generate(
        make_entry({"fan_min_speed": 150, "filament_max_volumetric_speed": 80, "filament_flow_ratio": 2, "cool_plate_temp": 120}),
        bambu,
        PRINTER,
    )
    spec = result.profile
    for key in ("fan_min_speed", "filament_max_volumetric_speed", "filament_flow_ratio", "cool_plate_temp"):
        assert key not in spec
    assert len(messages(result, "warning")) == 4


def test_generate_swapped_ranges_and_out_of_range_targets(bambu):
    result = generate(
        make_entry({"nozzle_temperature_range_low": 230, "nozzle_temperature_range_high": 190, "_bed_min": 70, "_bed_max": 50}),
        bambu,
        PRINTER,
    )
    assert result.ok
    assert sum("verdreht" in m for m in messages(result, "warning")) == 2
    result = generate(make_entry({"nozzle_temperature_range_low": 190, "nozzle_temperature_range_high": 200, "nozzle_temperature": 215}), bambu, PRINTER)
    assert any("außerhalb des Herstellerbereichs" in m for m in messages(result, "warning"))
    result = generate(make_entry({"nozzle_temperature": 250}), bambu, PRINTER)
    assert any("geerbten Bereichs" in m for m in messages(result, "warning"))


def test_generate_skips(bambu):
    system = bambu.system_keys(PRINTER)
    result = generate(make_entry(brand="Overture"), bambu, PRINTER, system)
    assert not result.ok and "Overture PLA" in messages(result, "info")[0]
    result = generate(make_entry(brand="Bambu Lab"), bambu, PRINTER)
    assert not result.ok and messages(result, "info")
    result = generate(make_entry(diameter=2.85), bambu, PRINTER)
    assert not result.ok and "Durchmesser" in messages(result, "error")[0]
    result = generate(make_entry(family="PEEK", name="PEEK"), bambu, PRINTER)
    assert not result.ok and "Basisprofil" in messages(result, "error")[0]


def test_generate_reports_conflicts(bambu):
    e = make_entry({"nozzle_temperature": 200})
    e.records.append(Record(source="orca", brand="Acme", material="PLA", name="PLA", ref="o", values={"nozzle_temperature": 230}))
    result = generate(e, bambu, PRINTER)
    assert result.profile["nozzle_temperature"] == ["230"]
    assert any("abweichend" in m for m in messages(result, "warning"))


def test_expand_to_root_preset(bambu):
    spec = generate(make_entry({"nozzle_temperature": 205}), bambu, PRINTER).profile
    root = expand(spec, bambu, "P1234567")
    assert root["inherits"] == "" and root["filament_id"] == "P1234567"
    assert root["nozzle_temperature"] == ["205"]
    assert root["filament_type"] == ["PLA"]
    assert root["filament_flow_ratio"] == ["0.98"]  # geerbt aus Generic PLA @base
    assert root["compatible_printers"] == [PRINTER]
    for key in ("setting_id", "instantiation", "type"):
        assert key not in root


def test_expand_replicates_variant_values(bambu):
    bambu.presets["Generic PLA"] = dict(bambu.presets["Generic PLA"], nozzle_temperature=["220", "225"])
    root = expand({"name": "X @P", "inherits": "Generic PLA", "nozzle_temperature": ["205"]}, bambu, "P1")
    assert root["nozzle_temperature"] == ["205", "205"]


def test_expand_missing_parent(bambu):
    with pytest.raises(ExpandError):
        expand({"name": "X", "inherits": "Gibt es nicht"}, bambu, "P1")


def test_product_name_uses_material_variant():
    assert product_name(make_entry(name="PLA", material="PLA+")) == "PLA+"
