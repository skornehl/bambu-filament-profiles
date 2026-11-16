"""Readers for the individual data sources.

Each reader gets the root folder of a (sparse) cloned source repo and returns a
list of :class:`~bambu_filament_profiles.model.Record`.
"""

from __future__ import annotations

import json
from pathlib import Path


def to_number(value) -> float | None:
    """Read a number from source values: "220", 220, ["220"], "95%" → 220.0 or 95.0."""
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


#: Errors a single malformed upstream file can cause while it is read or mapped.
DATA_ERRORS = (OSError, ValueError, TypeError, AttributeError, KeyError, IndexError)


def skip(problems: list[str] | None, path: Path, exc: Exception) -> None:
    """Note an unreadable file instead of aborting the whole build."""
    if problems is not None:
        problems.append(f"{path.name}: {exc}")
