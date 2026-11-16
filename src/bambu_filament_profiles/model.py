"""Data model shared by all sources.

Every source yields ``Record`` objects. Values already use Bambu Studio key
names (e.g. ``nozzle_temperature``). On top of that there are helper keys with a
leading underscore that the generator resolves:

``_bed`` / ``_bed_first``
    Bed temperature without a plate type (spread to Textured PEI and Smooth/Hot Plate).
``_bed_min`` / ``_bed_max``
    Bed range recommended by the manufacturer (only for checks and derived values).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Keys the generator takes from sources. Everything else is inherited from the
# Generic base profile.
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
    """One filament from exactly one source."""

    source: str
    brand: str
    material: str
    name: str
    ref: str
    values: dict[str, float] = field(default_factory=dict)
    diameter: float | None = None
    #: Names of slicer profiles the source itself refers to.
    links: set[str] = field(default_factory=set)
    #: Empty = all printers, otherwise only these Bambu printer profiles.
    compatible_printers: tuple[str, ...] = ()


@dataclass
class Entry:
    """One filament after matching all sources."""

    brand: str
    family: str
    name: str
    tokens: frozenset[str]
    material: str = ""
    records: list[Record] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return [r.source for r in self.records]
