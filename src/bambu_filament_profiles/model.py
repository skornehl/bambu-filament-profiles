"""Gemeinsames Datenmodell aller Quellen.

Jede Quelle liefert ``Record``-Objekte. Die Werte stehen bereits unter den
Schlüsselnamen von Bambu Studio (z. B. ``nozzle_temperature``). Zusätzlich gibt
es Hilfsschlüssel mit führendem Unterstrich, die der Generator auflöst:

``_bed`` / ``_bed_first``
    Betttemperatur ohne Plattentyp (wird auf Textured PEI und Smooth/Hot Plate verteilt).
``_bed_min`` / ``_bed_max``
    Vom Hersteller empfohlener Bettbereich (nur zur Prüfung und Ableitung).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Schlüssel, die der Generator aus Quellen übernimmt. Alles andere erbt vom
# Generic-Basisprofil.
VALUE_KEYS: tuple[str, ...] = (
    "filament_density",
    "nozzle_temperature",
    "nozzle_temperature_initial_layer",
    "nozzle_temperature_range_low",
    "nozzle_temperature_range_high",
    "hot_plate_temp",
    "hot_plate_temp_initial_layer",
    "textured_plate_temp",
    "textured_plate_temp_initial_layer",
    "cool_plate_temp",
    "cool_plate_temp_initial_layer",
    "eng_plate_temp",
    "eng_plate_temp_initial_layer",
    "supertack_plate_temp",
    "supertack_plate_temp_initial_layer",
    "fan_min_speed",
    "fan_max_speed",
    "overhang_fan_speed",
    "additional_cooling_fan_speed",
    "close_fan_the_first_x_layers",
    "fan_cooling_layer_time",
    "slow_down_layer_time",
    "slow_down_min_speed",
    "filament_max_volumetric_speed",
    "filament_flow_ratio",
    "filament_retraction_length",
    "filament_retraction_speed",
    "temperature_vitrification",
)

HELPER_KEYS: tuple[str, ...] = ("_bed", "_bed_first", "_bed_min", "_bed_max")

TEMPERATURE_KEYS = frozenset(
    {
        "nozzle_temperature",
        "nozzle_temperature_initial_layer",
        "nozzle_temperature_range_low",
        "nozzle_temperature_range_high",
        "hot_plate_temp",
        "hot_plate_temp_initial_layer",
        "textured_plate_temp",
        "textured_plate_temp_initial_layer",
        "cool_plate_temp",
        "cool_plate_temp_initial_layer",
        "eng_plate_temp",
        "eng_plate_temp_initial_layer",
        "supertack_plate_temp",
        "supertack_plate_temp_initial_layer",
        "_bed",
        "_bed_first",
        "_bed_min",
        "_bed_max",
    }
)


@dataclass
class Record:
    """Ein Filament aus genau einer Quelle."""

    source: str
    brand: str
    material: str
    name: str
    ref: str
    values: dict[str, float] = field(default_factory=dict)
    diameter: float | None = None
    #: Namen von Slicer-Profilen, auf die die Quelle selbst verweist.
    links: set[str] = field(default_factory=set)
    #: Leer = für alle Drucker, sonst nur für diese Bambu-Druckerprofile.
    compatible_printers: tuple[str, ...] = ()


@dataclass
class Entry:
    """Ein Filament nach dem Abgleich aller Quellen."""

    brand: str
    family: str
    name: str
    tokens: frozenset[str]
    material: str = ""
    records: list[Record] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return [r.source for r in self.records]
