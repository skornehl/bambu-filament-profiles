"""SpoolmanDB (``filaments/<brand>.json``): master data without slicer tuning values."""

from __future__ import annotations

import re
from pathlib import Path

from ..model import Record
from . import DATA_ERRORS, read_json, skip, to_number

FILAMENT_DIR = Path("filaments")


def load(root: Path, problems: list[str] | None = None) -> list[Record]:
    records = []
    for path in sorted((Path(root) / FILAMENT_DIR).glob("*.json")):
        try:
            records.extend(_load_file(path))
        except DATA_ERRORS as exc:
            skip(problems, path, exc)
    return records


def _pair(value) -> tuple[float, float] | None:
    """[low, high] → (low, high) if both are numbers."""
    if not isinstance(value, list) or len(value) != 2:
        return None
    low, high = to_number(value[0]), to_number(value[1])
    return None if low is None or high is None else (low, high)


def _load_file(path: Path) -> list[Record]:
    records = []
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
        low_high = _pair(item.get("extruder_temp_range"))
        if low_high:
            values["nozzle_temperature_range_low"], values["nozzle_temperature_range_high"] = low_high
        if to_number(item.get("bed_temp")) is not None:
            values["_bed"] = to_number(item["bed_temp"])
        bed_range = _pair(item.get("bed_temp_range"))
        if bed_range:
            values["_bed_min"], values["_bed_max"] = bed_range
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
