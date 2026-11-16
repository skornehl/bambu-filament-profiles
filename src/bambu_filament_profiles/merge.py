"""Match the sources and merge their values by priority."""

from __future__ import annotations

from dataclasses import dataclass, field

from .matching import match_key, norm_alias, norm_brand
from .model import TEMPERATURE_KEYS, Entry, Record

#: Who wins for tuning values (left = highest priority).
PRIORITY: tuple[str, ...] = ("manual", "orca", "prusa", "ofd", "spoolman", "cura")
#: Manufacturer data (master data): databases before slicer profiles.
MASTER_PRIORITY: tuple[str, ...] = ("manual", "ofd", "spoolman", "orca", "prusa", "cura")
MASTER_KEYS = frozenset(
    {"filament_density", "nozzle_temperature_range_low", "nozzle_temperature_range_high", "_bed_min", "_bed_max"}
)
#: From this difference (°C) between sources on, a value goes into the report.
CONFLICT_DELTA = 10.0

SOURCE_ORDER: tuple[str, ...] = ("ofd", "manual", "orca", "prusa", "spoolman", "cura")


@dataclass
class Conflict:
    key: str
    chosen_source: str
    chosen: float
    others: dict[str, float]


@dataclass
class Merged:
    values: dict[str, float] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)
    diameter: float | None = None


@dataclass
class Catalog:
    entries: list[Entry]
    unmatched: list[Record]


def build_catalog(records: dict[str, list[Record]]) -> Catalog:
    """Group the records of all sources into entries.

    The Open Filament Database is the skeleton. Other sources attach first via
    its references to slicer profiles, then via the match key; if nothing
    fits, a new entry is created.
    """
    entries: dict[tuple, Entry] = {}
    links: dict[str, tuple] = {}
    brand_display: dict[str, str] = {}
    unmatched: list[Record] = []

    for source in SOURCE_ORDER:
        for record in records.get(source, []):
            key = match_key(record.brand, record.material, record.name)
            if key is None:
                unmatched.append(record)
                continue
            target = None
            if source != "ofd":
                for candidate in (f"{record.brand} {record.name}", record.ref):
                    target = links.get(norm_alias(candidate))
                    if target:
                        break
                if target is None and key not in entries:
                    target = _unique_superset(entries, key)
            if target is None:
                target = key
            if target not in entries:
                brand = brand_display.setdefault(norm_brand(record.brand), record.brand)
                entries[target] = Entry(brand=brand, family=key[1], name=record.name, tokens=key[2], material=record.material)
            entries[target].records.append(record)
            for link in record.links:
                links.setdefault(norm_alias(link), target)
    return Catalog(entries=list(entries.values()), unmatched=unmatched)


def _unique_superset(entries: dict[tuple, Entry], key: tuple) -> tuple | None:
    """Less specific name ("Luminous") → the one more specific entry ("Luminous Glow")."""
    brand, family, toks = key
    if not toks:
        return None
    hits = [k for k in entries if k[0] == brand and k[1] == family and toks < k[2]]
    return hits[0] if len(hits) == 1 else None


def merge(entry: Entry) -> Merged:
    by_source: dict[str, list[Record]] = {}
    for record in entry.records:
        by_source.setdefault(record.source, []).append(record)
    result = Merged()
    keys = sorted({k for r in entry.records for k in r.values})
    for key in keys:
        order = MASTER_PRIORITY if key in MASTER_KEYS else PRIORITY
        candidates = [(s, r.values[key]) for s in order for r in by_source.get(s, []) if key in r.values]
        if not candidates:
            continue
        source, value = candidates[0]
        result.values[key] = value
        result.provenance[key] = source
        if key in TEMPERATURE_KEYS:
            others = {s: v for s, v in candidates[1:] if abs(v - value) > CONFLICT_DELTA}
            if others:
                result.conflicts.append(Conflict(key, source, value, others))
    for source in PRIORITY:
        for record in by_source.get(source, []):
            if record.diameter is not None:
                result.diameter = record.diameter
                return result
    return result
