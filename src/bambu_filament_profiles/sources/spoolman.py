"""SpoolmanDB (``filaments/<hersteller>.json``): Stammdaten ohne Slicer-Feinwerte."""

from __future__ import annotations

import re
from pathlib import Path

from ..model import Record
from . import read_json, to_number

FILAMENT_DIR = Path("filaments")


def load(root: Path) -> list[Record]:
    records = []
    for path in sorted((Path(root) / FILAMENT_DIR).glob("*.json")):
        data = read_json(path)
        brand = data.get("manufacturer") or path.stem
        seen: set[tuple[str, str]] = set()
        for item in data.get("filaments", []):
            material = item.get("material", "")
            name = re.sub(r"\s+", " ", re.sub(r"\{[^}]*\}", "", item.get("name", ""))).strip() or material
            if (material, name) in seen:
                continue
            seen.add((material, name))
            values: dict[str, float] = {}
            density = to_number(item.get("density"))
            if density is not None:
                values["filament_density"] = density
            if to_number(item.get("extruder_temp")) is not None:
                values["nozzle_temperature"] = to_number(item["extruder_temp"])
            low_high = item.get("extruder_temp_range") or []
            if len(low_high) == 2:
                values["nozzle_temperature_range_low"] = float(low_high[0])
                values["nozzle_temperature_range_high"] = float(low_high[1])
            if to_number(item.get("bed_temp")) is not None:
                values["_bed"] = to_number(item["bed_temp"])
            bed_range = item.get("bed_temp_range") or []
            if len(bed_range) == 2:
                values["_bed_min"] = float(bed_range[0])
                values["_bed_max"] = float(bed_range[1])
            diameters = [to_number(d) for d in item.get("diameters", [])]
            diameter = 1.75 if any(d and abs(d - 1.75) < 0.02 for d in diameters) else (diameters[0] if diameters else None)
            records.append(
                Record(
                    source="spoolman",
                    brand=brand,
                    material=material,
                    name=name,
                    ref=f"{path.name}: {item.get('name', '')}",
                    values=values,
                    diameter=diameter,
                )
            )
    return records
