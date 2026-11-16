"""OrcaSlicer filament library (``resources/profiles/OrcaFilamentLibrary``).

Manufacturer profiles with tuned values. Orca uses the same JSON schema as
Bambu Studio. Only values set by the manufacturer layer itself are used, not
those from Orca's own ``fdm_filament_*`` templates.
"""

from __future__ import annotations

from pathlib import Path

from ..matching import alias_of
from ..model import VALUE_KEYS, Record
from . import read_json, to_number

LIBRARY_DIR = Path("resources/profiles/OrcaFilamentLibrary/filament")


def _load_presets(root: Path) -> dict[str, dict]:
    presets: dict[str, dict] = {}
    for path in sorted((root / LIBRARY_DIR).rglob("*.json")):
        data = read_json(path)
        if isinstance(data, dict) and data.get("name"):
            presets[data["name"]] = data
    return presets


def _chain(presets: dict[str, dict], name: str) -> list[dict]:
    chain = []
    seen = set()
    while name and name not in seen:
        seen.add(name)
        preset = presets.get(name)
        if preset is None:
            break
        chain.append(preset)
        name = preset.get("inherits", "")
    return chain


def _resolve(chain: list[dict], key: str):
    for preset in chain:
        if key in preset:
            return preset[key]
    return None


def load(root: Path, printer: str) -> list[Record]:
    presets = _load_presets(Path(root))
    candidates: dict[str, list[tuple[dict, list[dict]]]] = {}
    for name, preset in presets.items():
        if preset.get("instantiation") != "true" or name.startswith("Generic"):
            continue
        chain = _chain(presets, name)
        vendor = (_resolve(chain, "filament_vendor") or [""])[0]
        if not vendor or vendor == "Generic":
            continue
        candidates.setdefault(alias_of(name), []).append((preset, chain))

    records = []
    for alias, variants in sorted(candidates.items()):
        chosen = _choose_variant(variants, printer)
        if chosen is None:
            continue
        preset, chain = chosen
        vendor = (_resolve(chain, "filament_vendor") or [""])[0]
        ftype = (_resolve(chain, "filament_type") or [""])[0]
        vendor_layers = [p for p in chain if not p["name"].startswith("fdm_filament")]
        values: dict[str, float] = {}
        for key in VALUE_KEYS:
            raw = _resolve(vendor_layers, key)
            number = to_number(raw)
            if number is not None:
                values[key] = number
        diameter = to_number(_resolve(chain, "filament_diameter"))
        product = alias[len(vendor):].strip() if alias.lower().startswith(vendor.lower()) else alias
        records.append(
            Record(
                source="orca",
                brand=vendor,
                material=ftype,
                name=product or ftype,
                ref=preset["name"],
                values=values,
                diameter=diameter,
                compatible_printers=tuple(_resolve(chain, "compatible_printers") or ()),
            )
        )
    return records


def _choose_variant(variants, printer: str):
    """Pick the variant for the target printer, otherwise the printer-independent one."""
    generic = None
    for preset, chain in variants:
        printers = _resolve(chain, "compatible_printers") or []
        if printer in printers:
            return preset, chain
        if not printers and generic is None:
            generic = (preset, chain)
    return generic
