"""Cura ``fdm_materials`` (XML je Farbe). Nur Temperaturen und Dichte.

Lüfter- und Rückzugswerte sind auf Ultimaker-Drucker (Bowden) abgestimmt und
werden nicht übernommen. Farben einer Sorte werden zusammengefasst.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import Record
from . import to_number

NS = {"m": "http://www.ultimaker.com/material"}
SKIP_BRANDS = {"ultimaker", "generic"}


def _text(root, path: str) -> str:
    node = root.find(path, NS)
    return (node.text or "").strip() if node is not None and node.text else ""


def load(root: Path) -> list[Record]:
    grouped: dict[tuple[str, str, str], Record] = {}
    for path in sorted(Path(root).glob("*.xml.fdm_material")):
        try:
            xml = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        brand = _text(xml, "m:metadata/m:name/m:brand")
        if not brand or brand.lower() in SKIP_BRANDS:
            continue
        diameter = to_number(_text(xml, "m:properties/m:diameter"))
        if diameter is None or abs(diameter - 1.75) > 0.02:
            continue
        material = _text(xml, "m:metadata/m:name/m:material")
        label = _text(xml, "m:metadata/m:name/m:label") or material
        color = _text(xml, "m:metadata/m:name/m:color")
        if color and label.lower().endswith(color.lower()):
            label = label[: -len(color)].strip()
        label = re.sub(r"\s+", " ", label) or material
        values: dict[str, float] = {}
        density = to_number(_text(xml, "m:properties/m:density"))
        if density is not None:
            values["filament_density"] = density
        for setting in xml.findall("m:settings/m:setting", NS):
            number = to_number(setting.text)
            if number is None:
                continue
            if setting.get("key") == "print temperature":
                values["nozzle_temperature"] = number
            elif setting.get("key") == "heated bed temperature":
                values["_bed"] = number
        key = (brand, material, label)
        if key not in grouped:
            grouped[key] = Record(source="cura", brand=brand, material=material, name=label, ref=path.name, values=values, diameter=1.75)
    return list(grouped.values())
