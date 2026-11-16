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
    assert limits_for("Other printer").bed_max == 100


def test_product_name():
    assert product_name(make_entry(name="Matte PLA")) == "Matte PLA"
    assert product_name(make_entry(name="Silk")) == "PLA Silk"
    assert product_name(make_entry(name="PLA")) == "PLA"
    assert product_name(make_entry(name="Red @Spool")) == "PLA Red at Spool"
    # Bambu Studio saves presets as <name>.json: no path or Windows-invalid characters
    assert product_name(make_entry(name="PA6/66", family="PA")) == "PA6-66"
    assert product_name(make_entry(name='PLA "Sparkly Green" |')) == "PLA Sparkly Green"


def test_generated_names_are_file_safe(bambu):
    result = generate(make_entry({"nozzle_temperature": 205}, brand="Hobby/Lobby", name="PLA Candy/Silver"), bambu, PRINTER)
    assert result.name == f"Hobby-Lobby PLA Candy-Silver @{PRINTER}"
    assert result.profile["filament_vendor"] == ["Hobby/Lobby"]


def test_choose_parent(bambu):
    assert choose_parent("PLA", frozenset(), bambu, PRINTER) == "Generic PLA"
    assert choose_parent("PLA", frozenset({"silk"}), bambu, PRINTER) == "Generic PLA Silk"
    assert choose_parent("PET", frozenset(), bambu, PRINTER) == "Generic PETG"
    assert choose_parent("PLA", frozenset({"cf"}), bambu, PRINTER) is None  # CF base is missing in the fixtures, no fallback to PLA
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
    assert spec["nozzle_temperature"] == ["200"]  # Generic 220 outside → middle
    assert result.provenance["nozzle_temperature"] == "derived"
    assert spec["textured_plate_temp"] == ["40"]  # Generic 55 outside 25–50
    assert any("derived" in m for m in messages(result, "info"))


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
    assert not result.ok and "bed" in messages(result, "error")[0]
    result = generate(make_entry({"_bed": 105}), bambu, PRINTER)
    assert not result.ok


def test_generate_clamps_upper_nozzle_bound(bambu):
    result = generate(make_entry({"nozzle_temperature_range_low": 260, "nozzle_temperature_range_high": 320}, family="PETG", name="PETG"), bambu, PRINTER)
    assert result.ok
    assert result.profile["nozzle_temperature_range_high"] == ["300"]
    assert any("capped" in m for m in messages(result, "warning"))


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
    assert sum("reversed" in m for m in messages(result, "warning")) == 2
    result = generate(make_entry({"nozzle_temperature_range_low": 190, "nozzle_temperature_range_high": 200, "nozzle_temperature": 215}), bambu, PRINTER)
    assert any("outside the manufacturer range" in m for m in messages(result, "warning"))
    result = generate(make_entry({"nozzle_temperature": 250}), bambu, PRINTER)
    assert any("inherited range" in m for m in messages(result, "warning"))


def test_generate_skips(bambu):
    system = bambu.system_keys(PRINTER)
    result = generate(make_entry(brand="Overture"), bambu, PRINTER, system)
    assert not result.ok and "Overture PLA" in messages(result, "info")[0]
    result = generate(make_entry(brand="Bambu Lab"), bambu, PRINTER)
    assert not result.ok and messages(result, "info")
    result = generate(make_entry(diameter=2.85), bambu, PRINTER)
    assert not result.ok and "diameter" in messages(result, "error")[0]
    result = generate(make_entry(family="PEEK", name="PEEK"), bambu, PRINTER)
    assert not result.ok and "base profile" in messages(result, "error")[0]


def test_generate_reports_conflicts(bambu):
    e = make_entry({"nozzle_temperature": 200})
    e.records.append(Record(source="orca", brand="Acme", material="PLA", name="PLA", ref="o", values={"nozzle_temperature": 230}))
    result = generate(e, bambu, PRINTER)
    assert result.profile["nozzle_temperature"] == ["230"]
    assert any("differing" in m for m in messages(result, "warning"))


def test_expand_to_root_preset(bambu):
    spec = generate(make_entry({"nozzle_temperature": 205}), bambu, PRINTER).profile
    root = expand(spec, bambu, "P1234567")
    assert root["inherits"] == "" and root["filament_id"] == "P1234567"
    assert root["nozzle_temperature"] == ["205"]
    assert root["filament_type"] == ["PLA"]
    assert root["filament_flow_ratio"] == ["0.98"]  # inherited from Generic PLA @base
    assert root["compatible_printers"] == [PRINTER]
    for key in ("setting_id", "instantiation", "type"):
        assert key not in root


def test_expand_replicates_variant_values(bambu):
    bambu.presets["Generic PLA"] = dict(bambu.presets["Generic PLA"], nozzle_temperature=["220", "225"])
    root = expand({"name": "X @P", "inherits": "Generic PLA", "nozzle_temperature": ["205"]}, bambu, "P1")
    assert root["nozzle_temperature"] == ["205", "205"]


def test_expand_missing_parent(bambu):
    with pytest.raises(ExpandError):
        expand({"name": "X", "inherits": "Does not exist"}, bambu, "P1")


def test_product_name_uses_material_variant():
    assert product_name(make_entry(name="PLA", material="PLA+")) == "PLA+"


def test_bed_range_beyond_printer_is_capped_not_rejected(bambu):
    # like 3DJAKE ABS: bed 100–110 °C; the midpoint 105 used to exceed the P1S limit of 100 °C
    result = generate(make_entry({"_bed_min": 100, "_bed_max": 110}), bambu, PRINTER)
    assert result.ok
    assert result.profile["textured_plate_temp"] == ["100"] and result.profile["hot_plate_temp"] == ["100"]
    result = generate(make_entry({"_bed_min": 95, "_bed_max": 120}), bambu, PRINTER)
    assert result.ok and result.profile["textured_plate_temp"] == ["100"]  # round5(97.5)
    result = generate(make_entry({"_bed_min": 105, "_bed_max": 120}), bambu, PRINTER)
    assert not result.ok and result.issues[-1].code == "bed"


def test_dropped_values_credit_no_source(bambu):
    e = make_entry({"nozzle_temperature": 205})
    e.records.append(Record(source="cura", brand="Acme", material="PLA", name="PLA", ref="c", values={"filament_density": 9.9}))
    result = generate(e, bambu, PRINTER)
    assert "cura" not in result.provenance.values()
    assert "Cura" not in result.profile["description"] and "Open Filament Database" in result.profile["description"]


def test_error_codes(bambu):
    assert generate(make_entry(diameter=2.85), bambu, PRINTER).issues[-1].code == "diameter"
    assert generate(make_entry(family="PEEK", name="PEEK"), bambu, PRINTER).issues[-1].code == "base_profile"
    assert generate(make_entry({"nozzle_temperature_range_low": 360}), bambu, PRINTER).issues[-1].code == "nozzle"
    assert generate(make_entry({"_bed": 105}), bambu, PRINTER).issues[-1].code == "bed"
