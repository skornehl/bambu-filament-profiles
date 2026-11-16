from bambu_filament_profiles.merge import build_catalog, merge
from bambu_filament_profiles.model import Entry, Record


def rec(source, brand="Acme", material="PLA", name="PLA", values=None, **kw):
    return Record(source=source, brand=brand, material=material, name=name, ref=f"{source}:{name}", values=values or {}, **kw)


def test_catalog_links_orca_via_ofd_reference(records):
    catalog = build_catalog(records)
    elegoo = next(e for e in catalog.entries if e.brand.lower() == "elegoo" and e.family == "PLA" and not e.tokens)
    assert sorted(set(elegoo.sources)) == ["ofd", "orca"]


def test_catalog_matches_spellings_and_keeps_first_brand_spelling():
    catalog = build_catalog(
        {
            "ofd": [rec("ofd", brand="eSUN 3D", name="PLA+")],
            "spoolman": [rec("spoolman", brand="eSUN", material="PLA+", name="PLA+")],
            "cura": [rec("cura", brand="esun", name="PLA Plus")],
        }
    )
    assert len(catalog.entries) == 1
    entry = catalog.entries[0]
    assert entry.brand == "eSUN 3D"
    assert entry.sources == ["ofd", "spoolman", "cura"]


def test_catalog_unique_superset_match_and_unmatched():
    catalog = build_catalog(
        {
            "ofd": [rec("ofd", name="Luminous Glow PLA"), rec("ofd", name="Silk PLA"), rec("ofd", name="Silk PLA Dual")],
            "spoolman": [rec("spoolman", name="Luminous"), rec("spoolman", name="Silk"), rec("spoolman", material="Holz", name="Holz")],
        }
    )
    by_name = {e.name: e for e in catalog.entries}
    assert by_name["Luminous Glow PLA"].sources == ["ofd", "spoolman"]
    # „Silk“ passt exakt zu „Silk PLA“ und nicht zum genaueren „Silk PLA Dual“
    assert by_name["Silk PLA"].sources == ["ofd", "spoolman"]
    assert [r.name for r in catalog.unmatched] == ["Holz"]


def test_superset_needs_unique_candidate():
    catalog = build_catalog(
        {
            "ofd": [rec("ofd", name="Matte Silk PLA"), rec("ofd", name="Matte Wood PLA")],
            "orca": [rec("orca", name="Matte")],
        }
    )
    assert len(catalog.entries) == 3


def entry(*records):
    e = Entry(brand="Acme", family="PLA", name="PLA", tokens=frozenset(), material="PLA")
    e.records.extend(records)
    return e


def test_merge_priority_and_master_keys():
    merged = merge(
        entry(
            rec("ofd", values={"nozzle_temperature_range_low": 190, "nozzle_temperature": 200, "filament_density": 1.24}),
            rec("orca", values={"nozzle_temperature_range_low": 180, "nozzle_temperature": 215, "filament_density": 1.3}),
        )
    )
    assert merged.values["nozzle_temperature"] == 215 and merged.provenance["nozzle_temperature"] == "orca"
    assert merged.values["nozzle_temperature_range_low"] == 190 and merged.provenance["nozzle_temperature_range_low"] == "ofd"
    assert merged.values["filament_density"] == 1.24
    assert merged.conflicts[0].key == "nozzle_temperature"
    assert merged.conflicts[0].others == {"ofd": 200}


def test_merge_no_conflict_within_delta_and_diameter():
    merged = merge(
        entry(
            rec("prusa", values={"nozzle_temperature": 210}, diameter=None),
            rec("spoolman", values={"nozzle_temperature": 205}, diameter=1.75),
            rec("cura", values={}, diameter=2.85),
        )
    )
    assert merged.conflicts == []
    assert merged.diameter == 1.75
    assert merge(entry(rec("ofd"))).diameter is None
