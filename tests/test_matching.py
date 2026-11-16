import pytest

from bambu_filament_profiles.matching import (
    alias_of,
    family_of,
    match_key,
    name_tokens,
    norm_alias,
    norm_brand,
    safe_filename,
    tokens,
)


@pytest.mark.parametrize(
    "brand, expected",
    [
        ("eSUN 3D", "esun"),
        ("esun_3d", "esun"),
        ("eSUN", "esun"),
        ("COEX 3D", "coex"),
        ("3D-Fuel", "3dfuel"),
        ("Bambu", "bambulab"),
        ("Bambu Lab", "bambulab"),
        ("Prusa Polymers", "prusament"),
        ("Add North", "addnorth"),
        ("", ""),
    ],
)
def test_norm_brand(brand, expected):
    assert norm_brand(brand) == expected


@pytest.mark.parametrize(
    "material, expected",
    [
        ("PLA", "PLA"),
        ("PLA+", "PLA"),
        ("PLA-CF", "PLA"),
        ("Matte PLA", "PLA"),
        ("HT-PLA", "PLA"),
        ("PETG", "PETG"),
        ("PETG-CF", "PETG"),
        ("PET-CF17", "PET"),
        ("PA6", "PA"),
        ("PA12-CF10", "PA"),
        ("PAHT-CF", "PA"),
        ("Nylon", "PA"),
        ("PPA-CF", "PPA"),
        ("PCTG", "PCTG"),
        ("PC", "PC"),
        ("FLEX", "TPU"),
        ("TPU 95A", "TPU"),
        ("CoPE", "PE"),
        ("PEEK", "PEEK"),
        ("PPS", "PPS"),
        ("PETGCF", "PETG"),
        ("Holz", None),
        ("", None),
    ],
)
def test_family_of(material, expected):
    assert family_of(material) == expected


def test_tokens_synonyms_and_stopwords():
    assert tokens("PLA+ High Speed Filament 1.75mm") == ["pla", "plus", "highspeed"]
    assert tokens("Carbon Rapid") == ["cf", "highspeed"]


def test_name_tokens_drops_brand_and_family():
    assert name_tokens("Elegoo PLA Matte", "Elegoo", "PLA") == {"matte"}
    assert name_tokens("PA6-CF", "Geeetech", "PA6") == {"cf"}
    assert name_tokens("Flexfill 98A", "Fillamentum", "FLEX") == {"flexfill", "98a"}


def test_name_tokens_plus_from_material_and_fibers():
    assert name_tokens("RAPID PLA+", "Elegoo", "PLA+") == {"highspeed", "plus"}
    assert name_tokens("Basic", "Brand", "PLA-CF") == {"basic", "cf"}


def test_match_key_equal_for_spellings():
    assert match_key("eSUN 3D", "PLA", "PLA+") == match_key("eSUN", "PLA+", "PLA Plus")
    assert match_key("X", "Holz", "Holz") is None
    assert match_key("X", "", "Matte PLA") == ("x", "PLA", frozenset({"matte"}))


def test_alias_and_norm_alias():
    assert alias_of("Elegoo PLA @System") == "Elegoo PLA"
    assert alias_of("eSUN PLA+ @BBL X1C") == "eSUN PLA+"
    assert norm_alias("SUNLU PLA+ 2.0 @System") == "sunlupla+20"


def test_safe_filename():
    assert safe_filename('A/B:C*D?"E<F>G|H') == "A-B-C-D--E-F-G-H"
    assert safe_filename("Name @Bambu Lab P1S 0.4 nozzle") == "Name @Bambu Lab P1S 0.4 nozzle"
    assert safe_filename("  ...  ") == "unbenannt"
    assert safe_filename("PLA  Silk.") == "PLA Silk"


def test_safe_filename_windows_reserved():
    assert safe_filename("CON") == "CON_"
    assert safe_filename("nul") == "nul_"
    assert safe_filename("Console") == "Console"


def test_carbon_fiber_matches_cf():
    assert name_tokens("PLA Carbon Fiber", "Sunlu", "PLA") == name_tokens("PLA CF", "Sunlu", "PLA") == {"cf"}
