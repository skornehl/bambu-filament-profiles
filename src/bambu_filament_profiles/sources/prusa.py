"""PrusaSlicer-settings, "Templates" bundle (``live/Templates/<version>.ini``).

Printer-independent filament templates from many manufacturers. Used are
temperatures (including the first layer), fans and density. Max volumetric
speed and flow ratio are tuned for Prusa hotends and are left out.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import Record
from . import to_number

TEMPLATES_DIR = Path("live/Templates")

VALUE_MAP = {
    "temperature": "nozzle_temperature",
    "first_layer_temperature": "nozzle_temperature_initial_layer",
    "bed_temperature": "_bed",
    "first_layer_bed_temperature": "_bed_first",
    "filament_density": "filament_density",
}

SKIP_VENDORS = {"Generic", ""}


def latest_bundle(root: Path) -> Path | None:
    bundles = list((Path(root) / TEMPLATES_DIR).glob("*.ini"))

    def version(path: Path):
        return tuple(int(p) if p.isdigit() else 0 for p in path.stem.split("."))

    return max(bundles, key=version) if bundles else None


def parse_ini(text: str) -> dict[tuple[str, str], dict[str, str]]:
    sections: dict[tuple[str, str], dict[str, str]] = {}
    current = None
    for line in text.splitlines():
        line = line.rstrip()
        header = re.match(r"^\[(\w+):(.+)\]$", line)
        if header:
            current = (header.group(1), header.group(2))
            sections[current] = {}
            continue
        if current is None or not line or line.startswith("#") or " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        sections[current][key.strip()] = value
    return sections


def resolve_sections(sections: dict[str, dict[str, str]], name: str, depth: int = 0) -> dict[str, str]:
    """Values of a section including inherited ones (``inherits = *A*; *B*``, later ones win)."""
    own = sections.get(name)
    if own is None or depth > 20:
        return {}
    merged: dict[str, str] = {}
    for parent in [p.strip() for p in own.get("inherits", "").split(";") if p.strip()]:
        merged.update(resolve_sections(sections, parent, depth + 1))
    merged.update(own)
    return merged


def load(root: Path) -> list[Record]:
    bundle = latest_bundle(root)
    if bundle is None:
        return []
    sections = {name: values for (kind, name), values in parse_ini(bundle.read_text(encoding="utf-8")).items() if kind == "filament"}
    records = []
    for name in sorted(sections):
        if name.startswith("*"):
            continue
        values = resolve_sections(sections, name)
        vendor = values.get("filament_vendor", "")
        if vendor in SKIP_VENDORS:
            continue
        numbers: dict[str, float] = {}
        for src, dst in VALUE_MAP.items():
            number = to_number(values.get(src))
            if number is not None and number > 0:
                numbers[dst] = number
        if values.get("cooling") == "1" or values.get("fan_always_on") == "1":
            for src, dst in (("min_fan_speed", "fan_min_speed"), ("max_fan_speed", "fan_max_speed")):
                number = to_number(values.get(src))
                if number is not None:
                    numbers[dst] = number
        product = name[len(vendor):].strip() if name.lower().startswith(vendor.lower()) else name
        records.append(
            Record(
                source="prusa",
                brand=vendor,
                material=values.get("filament_type", ""),
                name=product or values.get("filament_type", ""),
                ref=name,
                values=numbers,
                diameter=to_number(values.get("filament_diameter")),
            )
        )
    return records
