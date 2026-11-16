"""Your own values as TOML files in the ``manual/`` folder (highest priority).

Example ``manual/geeetech-pla.toml``::

    brand = "Geeetech"
    material = "PLA"
    name = "PLA"

    [values]
    nozzle_temperature = 205
    filament_flow_ratio = 0.98
    filament_max_volumetric_speed = 18
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from ..model import HELPER_KEYS, VALUE_KEYS, Record
from . import to_number

ALLOWED = set(VALUE_KEYS) | set(HELPER_KEYS)


class ManualError(ValueError):
    pass


def load(directory: Path) -> list[Record]:
    records = []
    if not Path(directory).is_dir():
        return records
    for path in sorted(Path(directory).glob("*.toml")):
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        missing = [k for k in ("brand", "material", "name") if not data.get(k)]
        if missing:
            raise ManualError(f"{path.name}: missing {', '.join(missing)}")
        values: dict[str, float] = {}
        for key, raw in (data.get("values") or {}).items():
            if key not in ALLOWED:
                raise ManualError(f"{path.name}: unknown key \"{key}\"")
            number = to_number(raw)
            if number is None:
                raise ManualError(f"{path.name}: \"{key}\" is not a number")
            values[key] = number
        records.append(
            Record(
                source="manual",
                brand=data["brand"],
                material=data["material"],
                name=data["name"],
                ref=path.name,
                values=values,
                diameter=to_number(data.get("diameter")),
            )
        )
    return records
