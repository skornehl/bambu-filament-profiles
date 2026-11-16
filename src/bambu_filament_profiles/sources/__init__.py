"""Leser für die einzelnen Datenquellen.

Jeder Leser bekommt das Wurzelverzeichnis eines (sparse) geklonten Quell-Repos
und liefert eine Liste von :class:`~bambu_filament_profiles.model.Record`.
"""

from __future__ import annotations

import json
from pathlib import Path


def to_number(value) -> float | None:
    """Zahl aus Quellwerten lesen: "220", 220, ["220"], "95%" → 220.0 bzw. 95.0."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("%")
    if not text or text.lower() == "nil":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
