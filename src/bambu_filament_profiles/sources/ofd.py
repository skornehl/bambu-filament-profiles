"""Open Filament Database (``data/<hersteller>/<MATERIAL>/<sorte>/filament.json``).

Das Gerüst des Katalogs: Hersteller, Material und Sorte sowie die vom
Hersteller angegebenen Bereiche für Düse und Bett, Dichte und weitere Werte.
"""

from __future__ import annotations

from pathlib import Path

from ..model import Record
from . import read_json, to_number

DATA_DIR = Path("data")

SIMPLE_MAP = {
    "density": "filament_density",
    "min_print_temperature": "nozzle_temperature_range_low",
    "max_print_temperature": "nozzle_temperature_range_high",
    "min_bed_temperature": "_bed_min",
    "max_bed_temperature": "_bed_max",
    "min_fan_speed": "fan_min_speed",
    "max_fan_speed": "fan_max_speed",
    "max_volumetric_speed": "filament_max_volumetric_speed",
}

SLICER_MAP = {
    "nozzle_temp": "nozzle_temperature",
    "first_layer_nozzle_temp": "nozzle_temperature_initial_layer",
    "bed_temp": "_bed",
    "first_layer_bed_temp": "_bed_first",
}


def load(root: Path) -> list[Record]:
    records = []
    data_dir = Path(root) / DATA_DIR
    for brand_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        brand_file = brand_dir / "brand.json"
        if not brand_file.exists():
            continue
        brand = read_json(brand_file).get("name") or brand_dir.name
        for material_dir in sorted(p for p in brand_dir.iterdir() if p.is_dir()):
            material_file = material_dir / "material.json"
            material = material_dir.name
            if material_file.exists():
                material = read_json(material_file).get("material") or material
            for filament_dir in sorted(p for p in material_dir.iterdir() if p.is_dir()):
                filament_file = filament_dir / "filament.json"
                if filament_file.exists():
                    records.append(_record(filament_file, brand, material, data_dir))
    return records


def _record(path: Path, brand: str, material: str, data_dir: Path) -> Record:
    data = read_json(path)
    values: dict[str, float] = {}
    for src, dst in SIMPLE_MAP.items():
        number = to_number(data.get(src))
        if number is not None:
            values[dst] = number
    slicer = data.get("slicer_settings") or {}
    for section in ("generic", "bambustudio"):
        settings = slicer.get(section) or {}
        for src, dst in SLICER_MAP.items():
            number = to_number(settings.get(src))
            if number is not None:
                values[dst] = number
    links = set()
    for section in ("bambustudio", "orcaslicer"):
        profile_name = (slicer.get(section) or {}).get("profile_name")
        if profile_name:
            links.add(profile_name)
    return Record(
        source="ofd",
        brand=brand,
        material=material,
        name=data.get("name") or path.parent.name,
        ref=path.parent.relative_to(data_dir).as_posix(),  # gleich unter Windows und Linux
        values=values,
        diameter=_diameter(path.parent),
        links=links,
    )


def _diameter(filament_dir: Path) -> float | None:
    """1,75 mm, wenn es eine Variante damit gibt, sonst den ersten Durchmesser."""
    found: list[float] = []
    for sizes in sorted(filament_dir.glob("*/sizes.json")):
        entries = read_json(sizes)
        for entry in entries if isinstance(entries, list) else []:
            number = to_number(entry.get("diameter"))
            if number is not None:
                found.append(number)
    if not found:
        return None
    return 1.75 if any(abs(d - 1.75) < 0.02 for d in found) else found[0]
